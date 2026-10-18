"""Harvey no Brasil (fork da LUME): português, LGPD, categorias do OpenStreetMap em português e o contato que a
própria empresa publica no site.

Liga com HARVEY_IDIOMA=pt-BR no ambiente. Sem ela, o Harvey se comporta como o original.
O rodapé de identificação e descadastro vem de HARVEY_RODAPE (texto pronto) — sem ele, nenhum e-mail sai em pt-BR.
"""

from __future__ import annotations

import os
import re
import unicodedata

ATIVO = os.getenv("HARVEY_IDIOMA", "").lower().startswith("pt")

IDIOMA = """

IDIOMA E LEI (vale sobre tudo acima): escreva todo texto que uma pessoa vai ler em português do Brasil, natural, como um
brasileiro escreve um e-mail curto para outro (sem tradução literal do inglês). Chaves de JSON, códigos de categoria e
nomes de campos continuam exatamente como pedido acima. O destinatário é uma empresa no Brasil: vale a LGPD (não a
CAN-SPAM/GDPR); trate a pessoa por você; sem "Prezado(a)", sem "venho por meio deste", sem "espero que esteja bem".
Quando o nome da pessoa não for conhecido (e-mail de contato da empresa), cumprimente sem nome ("Oi, tudo bem?") e fale
com a empresa pelo nome dela. Não escreva assinatura nem rodapé: eles são colocados depois, automaticamente.
"""


def com_idioma(prompt: str) -> str:
    return prompt + IDIOMA if ATIVO and IDIOMA not in prompt else prompt


# Pedidos de descadastro e o que precisa de um humano (somados às listas em inglês do handler).
OPT_OUT = (
    "sair", "descadastr", "remover meu", "remova meu", "me remova", "me tira", "me tire", "tirar meu e-mail",
    "não quero receber", "nao quero receber", "pare de enviar", "parem de enviar", "pare de mandar", "não me mande",
    "nao me mande", "não envie mais", "nao envie mais", "cancelar inscrição", "cancelar inscricao", "spam",
)
ESCALAR = (
    "lgpd", "anpd", "procon", "advogado", "processo judicial", "processar", "denúncia", "denuncia", "denunciar", "assédio",
    "assedio", "ministério público", "reclame aqui", "polícia", "policia",
)
# Clichês de e-mail frio em português (o gate barra, como faz com os em inglês).
FRASES_PROIBIDAS = (
    "espero que esteja bem", "espero que este e-mail", "venho por meio deste", "prezado", "prezada",
    "gostaria de apresentar", "oportunidade imperdível", "oportunidade unica", "oportunidade única", "clique aqui",
    "não perca", "nao perca", "garantia de resultado", "resultado garantido", "100% grátis", "100% gratis",
    "promoção imperdível", "sou uma ia", "como uma ia", "como modelo de linguagem",
)

# Categorias em português → as tags do OpenStreetMap (procura por pedaço do termo, sem acento).
TAG_MAP_PT = {
    "dentist": ["amenity=dentist"], "odonto": ["amenity=dentist"],
    "estetic": ["shop=beauty", "amenity=clinic"], "beleza": ["shop=beauty"], "salao": ["shop=hairdresser", "shop=beauty"],
    "barbear": ["shop=hairdresser"], "cabelei": ["shop=hairdresser"],
    "advoca": ["office=lawyer"], "advogad": ["office=lawyer"], "juridic": ["office=lawyer"],
    "pousada": ["tourism=guest_house"], "hotel": ["tourism=hotel"], "hostel": ["tourism=hostel"],
    "oficina": ["shop=car_repair"], "mecanic": ["shop=car_repair"], "autopec": ["shop=car_parts"],
    "clinica": ["amenity=clinic"], "fisioter": ["healthcare=physiotherapist"], "psicolog": ["healthcare=psychotherapist"],
    "veterin": ["amenity=veterinary"], "pet shop": ["shop=pet"], "academia": ["leisure=fitness_centre"],
    "restaurant": ["amenity=restaurant"], "cafeter": ["amenity=cafe"], "padaria": ["shop=bakery"],
    "imobili": ["office=estate_agent"], "contabil": ["office=accountant"], "contador": ["office=accountant"],
    "agencia de marketing": ["office=advertising_agency"], "agencia de publicidade": ["office=advertising_agency"],
    "agencia": ["office=advertising_agency"], "produtora": ["craft=photographer", "shop=photo"],
    "fotograf": ["craft=photographer"], "otica": ["shop=optician"], "farmac": ["amenity=pharmacy"],
}


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c))


def tags_osm(termo: str) -> list[str]:
    baixo = sem_acento(termo).lower()
    for pedaco, tags in TAG_MAP_PT.items():
        if pedaco in baixo:
            return tags
    return []


# Páginas de equipe e contato dos sites brasileiros.
PAGINAS_EQUIPE = ["/sobre", "/quem-somos", "/equipe", "/nossa-equipe", "/a-clinica", "/o-escritorio", "/time"]
PAGINAS_CONTATO = ["/contato", "/fale-conosco", "/contatos", "/atendimento"]

# ── o contato publicado no site (e-mail, Instagram, WhatsApp) ──

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_INSTA = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})", re.I)
_WHATS = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=|whatsapp\.com/send/\?phone=)\+?(\d{10,13})", re.I)
GRATUITOS = {"gmail.com", "hotmail.com", "outlook.com", "live.com", "yahoo.com", "yahoo.com.br", "uol.com.br",
             "bol.com.br", "terra.com.br", "icloud.com", "msn.com"}
_NAO_E_EMAIL = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".js", ".css")
_INSTA_NAO = {"p", "reel", "reels", "explore", "stories", "accounts", "tv", "share", "direct", "about", "legal"}
_PREFERIDOS = ("contato", "atendimento", "comercial", "agendamento", "agenda", "recepcao", "clinica", "escritorio", "ola", "oi")


def contatos_do_site(html: str, dominio: str) -> dict:
    """O que a empresa publica no próprio site: { emails: [...], instagram: str|None, whatsapp: str|None }.

    Vale o e-mail do domínio dela ou de um provedor gratuito (o dono que usa Gmail), nunca de terceiros (a agência que
    fez o site, um plugin). O primeiro é o melhor para escrever (contato@, atendimento@... antes de outros).
    """
    dominio = (dominio or "").lower().removeprefix("www.")
    achados: list[str] = []
    for m in re.findall(r'mailto:([^"\'?\s>]+)', html, re.I) + _EMAIL.findall(html):
        e = m.strip().strip(".").lower()
        if "@" not in e or e.endswith(_NAO_E_EMAIL) or e in achados:
            continue
        dom = e.split("@", 1)[1]
        if dom == dominio or dom.endswith("." + dominio) or dom in GRATUITOS:
            if not re.search(r"(sentry|wixpress|example|exemplo|seuemail|seu-email|email@)", e):
                achados.append(e)
    achados.sort(key=lambda e: (0 if e.split("@")[0].startswith(_PREFERIDOS) else 1, len(e)))
    insta = next((h for h in _INSTA.findall(html) if h.lower() not in _INSTA_NAO), None)
    whats = next(iter(_WHATS.findall(html)), None)
    return {"emails": achados[:3], "instagram": insta, "whatsapp": whats}


def rodape() -> str:
    """A identificação e o descadastro no fim de todo e-mail (LGPD; o Gmail pede o descadastro fácil)."""
    texto = os.getenv("HARVEY_RODAPE", "").replace("\\n", "\n").strip()
    return f"\n\n--\n{texto}" if texto else ""
