"""Fork LUME: as pontes com o LUME Hub.

  python -m harvey.br_importar importar < empresas.json
      As empresas do Prospector do Hub (dados públicos do Google): entram como empresas, sem repetir (pelo domínio ou
      pelo id do Prospector), com a nota e as avaliações do Google como sinais. O contato sai depois, do próprio site
      (collectors/br_contatos). Entrada: [{ id, nome, cidade, uf, website_uri, social_url, phone_e164, has_whatsapp,
      rating, user_rating_count }]. Saída: { "novas": n, "repetidas": n }.

  python -m harvey.br_importar instagrams
      As empresas com Instagram achado (no site ou no Prospector), para a fila do Social Selling no Hub:
      [{ handle, nome, site, nicho, email, whatsapp, notas }].
"""

from __future__ import annotations

import asyncio
import json
import re
import sys

from harvey import br
from harvey.collectors.discover import normalize_domain
from harvey.models.company import Company
from harvey.state import StateManager

NICHOS = (
    (r"odont|dent|sorriso|oral|implant|ortodon", "Clínica odontológica"),
    (r"advoca|advogad|jur[ií]dic|direito", "Escritório de advocacia"),
    (r"est[eé]tic|beleza|harmoniza|depila", "Clínica de estética"),
    (r"ag[eê]ncia|marketing|produtora|filmes|publicidade|comunica[cç]|digital|social media|tr[aá]fego", "Agência de marketing"),
    (r"pousada|hotel|hostel", "Pousada"),
    (r"oficina|mec[aâ]nic|auto ?center|funilaria", "Oficina mecânica"),
)


def nicho_do_nome(nome: str) -> str:
    baixo = br.sem_acento(nome or "").lower()
    return next((n for padrao, n in NICHOS if re.search(br.sem_acento(padrao), baixo)), "Negócio local")


def instagram_de(url: str) -> str | None:
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]{2,30})", url or "", re.I)
    return m.group(1).lower() if m and m.group(1).lower() not in br._INSTA_NAO else None


async def importar(itens: list[dict]) -> dict:
    s = StateManager()
    await s.init_db()
    novas = repetidas = 0
    for x in itens:
        dominio = normalize_domain(x.get("website_uri") or "")
        if not dominio or not x.get("nome"):
            continue
        externo = f"prospector:{x.get('id')}"
        if await s.get_company_by_external_id(externo) or await s.get_company_by_domain(dominio):
            repetidas += 1
            continue
        local = ", ".join(v for v in (x.get("cidade"), x.get("uf")) if v)
        cid = await s.add_company(Company(
            name=str(x["nome"])[:200], domain=dominio, website=x.get("website_uri") or "", phone=x.get("phone_e164") or "",
            location=local, industry=nicho_do_nome(x["nome"]), source="prospector", external_id=externo,
            source_url=x.get("maps_uri") or "",
        ))
        sinais = []
        if x.get("rating") and x.get("user_rating_count"):
            sinais.append({"type": "google", "detail": f"nota {x['rating']} no Google com {x['user_rating_count']} avaliações"})
        if instagram_de(x.get("social_url") or ""):
            sinais.append({"type": "instagram", "detail": f"@{instagram_de(x['social_url'])}"})
        if x.get("has_whatsapp") and x.get("phone_e164"):
            sinais.append({"type": "whatsapp", "detail": re.sub(r"\D", "", x["phone_e164"])})
        if sinais:
            await s.update_company_signals(cid, new_signals=sinais)
        novas += 1
    return {"novas": novas, "repetidas": repetidas}


async def instagrams() -> list[dict]:
    s = StateManager()
    await s.init_db()
    import aiosqlite

    async with aiosqlite.connect(s.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT c.id, c.name, c.website, c.industry, c.location, c.signals_json,
                      (SELECT p.email FROM prospects p WHERE p.company_id = c.id AND p.email != '' LIMIT 1) AS email
                 FROM companies c WHERE c.signals_json LIKE '%"instagram"%'"""
        ) as cur:
            linhas = [dict(r) for r in await cur.fetchall()]
    saida = []
    for r in linhas:
        try:
            sinais = json.loads(r["signals_json"] or "[]")
        except ValueError:
            continue
        handle = next((str(x.get("detail", "")).lstrip("@") for x in sinais if x.get("type") == "instagram"), "")
        if not handle:
            continue
        whats = next((x.get("detail") for x in sinais if x.get("type") == "whatsapp"), None)
        google = next((x.get("detail") for x in sinais if x.get("type") == "google"), None)
        saida.append({
            "handle": handle, "nome": r["name"], "site": r["website"], "nicho": r["industry"], "email": r["email"],
            "whatsapp": whats,
            "notas": "Achado pela prospecção por e-mail (Harvey)" + (f" · {r['location']}" if r["location"] else "") + (f" · {google}" if google else ""),
        })
    return saida


def main():
    comando = sys.argv[1] if len(sys.argv) > 1 else ""
    if comando == "importar":
        itens = json.load(sys.stdin)
        print(json.dumps(asyncio.run(importar(itens if isinstance(itens, list) else itens.get("leads", [])))))
    elif comando == "instagrams":
        print(json.dumps(asyncio.run(instagrams()), ensure_ascii=False))
    else:
        raise SystemExit("uso: python -m harvey.br_importar importar|instagrams")


if __name__ == "__main__":
    main()
