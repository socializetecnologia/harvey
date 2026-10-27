"""O contato que a empresa publica no próprio site (fork da LUME, para pequenas empresas no Brasil).

Pequeno negócio brasileiro raramente tem página de equipe; o que existe é o e-mail de contato (contato@, atendimento@,
ou o Gmail do dono) na home ou na página de contato. Para cada empresa com site e sem contato: lê a home e as páginas de
contato, cria o contato com o melhor e-mail e guarda o Instagram e o WhatsApp como sinais da empresa (a LUME leva o
Instagram para a fila do Hub). Sem chamada ao modelo: só HTTP, regex, DNS e SMTP.

Publicado não quer dizer que ainda existe: site de pequeno negócio guarda e-mail de anos atrás. Quando todo endereço do
site virava "verified", 8 de 46 voltaram e o freio de devolução (5%) parou os envios. Agora cada endereço passa pelo MX
e pelo teste de SMTP do email_finder antes de ser enviável (`situacao`), e os contatos antigos são conferidos aos poucos
(`reverificar`).
"""

from __future__ import annotations

import asyncio
import logging

import aiosqlite
import httpx

from harvey import br
from harvey.integrations import email_finder
from harvey.models.prospect import Prospect

logger = logging.getLogger(__name__)


async def situacao(email: str) -> str:
    """verified | risky | invalid para um e-mail publicado no site (o Sender só manda para verified)."""
    mx = await email_finder.get_mx_host(email.rsplit("@", 1)[-1])
    if not mx:
        return "invalid"  # domínio sem servidor de e-mail: volta com certeza
    tipo = email_finder.classify_mx(mx)
    status, _ = await email_finder._verify_candidate(email, tipo, None)
    if status:
        return status
    # Google e Microsoft não respondem ao teste de SMTP; num provedor grande o endereço publicado quase sempre existe.
    # Nos outros, sem resposta é risco: não sai (send_to_risky: false).
    return "verified" if tipo in ("google", "microsoft") else "risky"


async def reverificar(state, limite: int = 30) -> int:
    """Confere os contatos criados antes da verificação (fonte site_publicado) que ainda não receberam nada; o que
    não passa sai da fila. Marca a fonte como site_verificado para não repetir. Devolve quantos deixaram de ser enviáveis."""
    async with aiosqlite.connect(state.db_path) as db:
        async with db.execute(
            "SELECT id, email FROM prospects WHERE source = 'site_publicado' AND email != '' "
            "AND id NOT IN (SELECT prospect_id FROM outbox WHERE status = 'sent' AND prospect_id IS NOT NULL) LIMIT ?",
            (int(limite),),
        ) as cursor:
            linhas = await cursor.fetchall()
    tirados = 0
    for pid, email in linhas:
        try:
            st = await situacao(email)
            await state.update_prospect_email(pid, email, st)
            if st != "verified":
                tirados += 1
                await state.cancel_pending_outbox_for_prospect(pid, reason=f"email {st}")
            async with aiosqlite.connect(state.db_path) as db:
                await db.execute("UPDATE prospects SET source = 'site_verificado' WHERE id = ?", (pid,))
                await db.commit()
        except Exception as e:  # um contato ruim não para os outros
            logger.warning("br_contatos: reverificar %s: %s", pid, e)
    if linhas:
        logger.info("br_contatos: %d contatos antigos conferidos, %d fora da fila", len(linhas), tirados)
    return tirados

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


async def coletar(state, limite: int = 15) -> int:
    """Devolve quantos contatos novos criou."""
    await reverificar(state)
    empresas = await state.companies_needing_prospects(limit=limite)
    if not empresas:
        return 0
    criados = 0
    headers = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5", "Accept": "text/html,*/*;q=0.5"}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as cliente:
        for c in empresas:
            achado = {"emails": [], "instagram": None, "whatsapp": None, "pagina": ""}
            for caminho in ["", *br.PAGINAS_CONTATO]:
                try:
                    r = await cliente.get(f"https://{c['domain']}{caminho}")
                except httpx.HTTPError:
                    continue
                if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                    continue
                d = br.contatos_do_site(r.text[:400_000], c["domain"])
                for e in d["emails"]:
                    if e not in achado["emails"]:
                        achado["emails"].append(e)
                        achado["pagina"] = achado["pagina"] or str(r.url)
                achado["instagram"] = achado["instagram"] or d["instagram"]
                achado["whatsapp"] = achado["whatsapp"] or d["whatsapp"]
                if achado["emails"] and caminho:
                    break  # a home e a primeira página de contato com e-mail bastam
                await asyncio.sleep(0.5)
            try:
                # o primeiro endereço que existe de fato; sem nenhum, o melhor arriscado (fica fora dos envios)
                escolhido = None
                for e in achado["emails"]:
                    st = await situacao(e)
                    if st == "verified":
                        escolhido = (e, st)
                        break
                    if st == "risky" and not escolhido:
                        escolhido = (e, st)
                if escolhido and not await state.get_prospect_by_email(escolhido[0]):
                    await state.add_prospect(Prospect(
                        company_id=c["id"], company=c["name"], industry=c.get("industry") or "",
                        email=escolhido[0], email_status=escolhido[1], email_verified=escolhido[1] == "verified",
                        title="contato da empresa", source="site_verificado", source_url=achado["pagina"],
                    ))
                    criados += 1
                sinais = []
                if achado["instagram"]:
                    sinais.append({"type": "instagram", "detail": f"@{achado['instagram']}"})
                if achado["whatsapp"]:
                    sinais.append({"type": "whatsapp", "detail": achado["whatsapp"]})
                if sinais:
                    await state.update_company_signals(c["id"], new_signals=sinais)
                await state.mark_prospects_checked(c["id"])
            except Exception as e:  # uma empresa ruim não para as outras
                logger.warning("br_contatos: %s: %s", c.get("domain"), e)
            await asyncio.sleep(1.0)
    if criados:
        logger.info("br_contatos: %d contatos novos (e-mail publicado no site)", criados)
    return criados
