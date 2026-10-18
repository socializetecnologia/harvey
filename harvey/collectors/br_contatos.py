"""O contato que a empresa publica no próprio site (fork da LUME, para pequenas empresas no Brasil).

Pequeno negócio brasileiro raramente tem página de equipe; o que existe é o e-mail de contato (contato@, atendimento@,
ou o Gmail do dono) na home ou na página de contato. Esse endereço foi publicado pela própria empresa para receber
mensagem, então vale como entregável sem verificador pago. Para cada empresa com site e sem contato: lê a home e as
páginas de contato, cria o contato com o melhor e-mail e guarda o Instagram e o WhatsApp como sinais da empresa (a LUME
leva o Instagram para a fila do Hub). Sem chamada ao modelo: só HTTP e regex.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from harvey import br
from harvey.models.prospect import Prospect

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


async def coletar(state, limite: int = 15) -> int:
    """Devolve quantos contatos novos criou."""
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
                if achado["emails"] and not await state.get_prospect_by_email(achado["emails"][0]):
                    await state.add_prospect(Prospect(
                        company_id=c["id"], company=c["name"], industry=c.get("industry") or "",
                        email=achado["emails"][0], email_status="verified", email_verified=True,
                        title="contato da empresa", source="site_publicado", source_url=achado["pagina"],
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
