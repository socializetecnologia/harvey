"""O fork da LUME: português, LGPD, OpenStreetMap em português e o contato publicado no site."""

import asyncio

from harvey import br


def test_contatos_do_site_pega_o_email_da_empresa_e_ignora_terceiros():
    html = """
      <a href="mailto:Contato@ClinicaSorriso.com.br?subject=oi">fale</a>
      <p>ou dra.ana@gmail.com</p>
      <footer>site feito por <a href="mailto:oi@agenciaqualquer.com">agência</a></footer>
      <img src="logo@2x.png"> <a href="https://www.instagram.com/clinicasorriso/">insta</a>
      <a href="https://instagram.com/p/abc123">post</a>
      <a href="https://wa.me/5521999998888">whats</a>
    """
    d = br.contatos_do_site(html, "www.clinicasorriso.com.br")
    assert d["emails"] == ["contato@clinicasorriso.com.br", "dra.ana@gmail.com"]
    assert d["instagram"] == "clinicasorriso"
    assert d["whatsapp"] == "5521999998888"


def test_contatos_do_site_prefere_contato_e_atendimento():
    d = br.contatos_do_site("financeiro@x.com.br ana@x.com.br atendimento@x.com.br", "x.com.br")
    assert d["emails"][0] == "atendimento@x.com.br"
    assert br.contatos_do_site("<p>nada aqui</p>", "x.com.br") == {"emails": [], "instagram": None, "whatsapp": None}


def test_categorias_em_portugues_sem_acento():
    assert br.tags_osm("Clínica odontológica") == ["amenity=dentist"]
    assert br.tags_osm("Barbearia") == ["shop=hairdresser"]
    assert br.tags_osm("Escritório de advocacia") == ["office=lawyer"]
    assert br.tags_osm("Agência de marketing") == ["office=advertising_agency"]
    assert br.tags_osm("Pousada") == ["tourism=guest_house"]
    assert br.tags_osm("Oficina mecânica") == ["shop=car_repair"]
    assert br.tags_osm("algo que não existe") == []
    assert br.sem_acento("João Antônio") == "Joao Antonio"


def test_idioma_e_rodape(monkeypatch):
    monkeypatch.setattr(br, "ATIVO", True)
    p = br.com_idioma("Write ONE cold email.")
    assert p.endswith(br.IDIOMA) and br.com_idioma(p) == p  # não repete
    monkeypatch.setenv("HARVEY_RODAPE", "Henrique Sampaio · LUME\\nPara não receber mais, responda SAIR.")
    assert br.rodape() == "\n\n--\nHenrique Sampaio · LUME\nPara não receber mais, responda SAIR."
    monkeypatch.setattr(br, "ATIVO", False)
    assert br.com_idioma("x") == "x"


def test_descadastro_em_portugues():
    texto = "por favor me remova da lista, não quero receber mais"
    assert any(p in texto for p in br.OPT_OUT)
    assert not any(p in "qual o processo de vocês para agendar?" for p in br.ESCALAR)
    assert any(p in "vou denunciar no procon" for p in br.ESCALAR)


def test_coletor_cria_o_contato_publicado(monkeypatch):
    from harvey.collectors import br_contatos

    criados, sinais, vistos = [], [], []

    class Estado:
        async def companies_needing_prospects(self, limit=10):
            return [{"id": "c1", "name": "Clínica Sorriso", "domain": "clinicasorriso.com.br", "industry": "dentista"}]

        async def get_prospect_by_email(self, e):
            return None

        async def add_prospect(self, p):
            criados.append(p)

        async def update_company_signals(self, cid, new_signals=None):
            sinais.extend(new_signals)

        async def mark_prospects_checked(self, cid):
            vistos.append(cid)

    class Resp:
        status_code = 200
        headers = {"content-type": "text/html"}
        url = "https://clinicasorriso.com.br/contato"
        text = '<a href="mailto:contato@clinicasorriso.com.br">e-mail</a> <a href="https://instagram.com/clinicasorriso">ig</a>'

    class Cliente:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return Resp()

    monkeypatch.setattr(br_contatos.httpx, "AsyncClient", Cliente)
    dormir = asyncio.sleep
    monkeypatch.setattr(br_contatos.asyncio, "sleep", lambda s: dormir(0))

    async def nada(state, limite=30):
        return 0

    async def verificado(e):
        return "verified"

    monkeypatch.setattr(br_contatos, "reverificar", nada)
    monkeypatch.setattr(br_contatos, "situacao", verificado)
    assert asyncio.run(br_contatos.coletar(Estado())) == 1
    assert criados[0].email == "contato@clinicasorriso.com.br" and criados[0].email_status == "verified"
    assert criados[0].source == "site_verificado"
    assert {"type": "instagram", "detail": "@clinicasorriso"} in sinais
    assert vistos == ["c1"]


def test_situacao_confere_mx_e_smtp_antes_de_enviar(monkeypatch):
    """O e-mail publicado no site só vira enviável se o domínio recebe e-mail e o servidor não recusa a caixa."""
    from harvey.collectors import br_contatos
    from harvey.integrations import email_finder

    mx = {"morto.com.br": None, "gmail.com": "gmail-smtp-in.l.google.com", "hostinger.com.br": "mx1.hostinger.com.br"}
    smtp = {"sumiu@hostinger.com.br": ("invalid", False), "ok@hostinger.com.br": ("verified", False)}

    async def get_mx_host(d):
        return mx[d]

    async def verify(e, tipo, env):
        return smtp.get(e, (None, False))

    monkeypatch.setattr(email_finder, "get_mx_host", get_mx_host)
    monkeypatch.setattr(email_finder, "_verify_candidate", verify)
    s = lambda e: asyncio.run(br_contatos.situacao(e))
    assert s("contato@morto.com.br") == "invalid"  # domínio sem servidor de e-mail
    assert s("sumiu@hostinger.com.br") == "invalid"  # o servidor recusou a caixa
    assert s("ok@hostinger.com.br") == "verified"
    assert s("talvez@hostinger.com.br") == "risky"  # sem resposta num servidor pequeno: não sai
    assert s("dono@gmail.com") == "verified"  # provedor grande não responde ao teste; publicado vale


def test_reverificar_tira_da_fila_o_contato_antigo_que_nao_existe(monkeypatch, tmp_path):
    import sqlite3

    from harvey.collectors import br_contatos

    banco = tmp_path / "h.db"
    db = sqlite3.connect(banco)
    db.executescript("""
      CREATE TABLE prospects (id TEXT, email TEXT, source TEXT);
      CREATE TABLE outbox (prospect_id TEXT, status TEXT);
      INSERT INTO prospects VALUES ('p1', 'velho@x.com.br', 'site_publicado'), ('p2', 'bom@x.com.br', 'site_publicado'),
        ('p3', 'ja@x.com.br', 'site_publicado'), ('p4', 'outro@x.com.br', 'apollo');
      INSERT INTO outbox VALUES ('p3', 'sent');
    """)
    db.commit()
    db.close()
    status, cancelados = {}, []

    class Estado:
        db_path = str(banco)

        async def update_prospect_email(self, pid, email, st):
            status[pid] = st

        async def cancel_pending_outbox_for_prospect(self, pid, reason=""):
            cancelados.append(pid)

    async def situacao(e):
        return "invalid" if e.startswith("velho") else "verified"

    monkeypatch.setattr(br_contatos, "situacao", situacao)
    assert asyncio.run(br_contatos.reverificar(Estado())) == 1
    assert status == {"p1": "invalid", "p2": "verified"}  # quem já recebeu e quem não veio do site ficam de fora
    assert cancelados == ["p1"]
    fontes = dict(sqlite3.connect(banco).execute("SELECT id, source FROM prospects").fetchall())
    assert fontes == {"p1": "site_verificado", "p2": "site_verificado", "p3": "site_publicado", "p4": "apollo"}
    assert asyncio.run(br_contatos.reverificar(Estado())) == 0  # não repete


def test_leitura_da_caixa_nao_marca_nada_e_so_traz_as_respostas(monkeypatch):
    """A caixa é a de verdade do dono: só leitura, só PEEK e só o que é resposta ao Harvey, devolução ou prospectado."""
    from harvey.integrations import smtp_mail

    cab = {
        b"1": b"From: Banco <avisos@banco.com.br>\r\nSubject: fatura\r\n\r\n",
        b"2": b"From: Ana <contato@sorriso.com.br>\r\nSubject: Re: mapa\r\nIn-Reply-To: <abc@wearelume.com.br>\r\n\r\n",
        b"3": b"From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>\r\nSubject: Delivery Status Notification (Failure)\r\n\r\n",
        b"4": b"From: <dono@oficina.com.br>\r\nSubject: oi\r\n\r\n",
    }
    chamadas = []

    class Conn:
        def __init__(self, *a):
            pass

        def login(self, *a):
            pass

        def select(self, caixa, readonly=False):
            chamadas.append(("select", readonly))
            return "OK", [b"4"]

        def search(self, *a):
            chamadas.append(("search", a))
            return "OK", [b"1 2 3 4"]

        def fetch(self, ids, partes):
            chamadas.append(("fetch", partes))
            if "HEADER.FIELDS" in partes:
                return "OK", [(k + b" (BODY[HEADER] {10}", v) for k, v in cab.items()]
            return "OK", [(ids + b" (BODY[] {10}", cab[ids] + b"corpo")]

        def logout(self):
            pass

    monkeypatch.setattr(smtp_mail.imaplib, "IMAP4_SSL", Conn)
    p = smtp_mail.SmtpImapProvider.__new__(smtp_mail.SmtpImapProvider)
    p.imap_host, p.imap_port, p.imap_user, p.imap_pass, p.smtp_user = "h", 993, "u", "s", "contato@wearelume.com.br"

    class P:
        email = "contato@wearelume.com.br"

    class C:
        persona = P()

    p.config = C()
    p.remetentes_conhecidos = {"dono@oficina.com.br"}
    msgs = p._buscar_respostas(50)
    assert sorted(m.from_email for m in msgs) == ["contato@sorriso.com.br", "dono@oficina.com.br", "mailer-daemon@googlemail.com"]
    assert ("select", True) in chamadas
    assert all("RFC822" not in c[1] for c in chamadas if c[0] == "fetch")  # nada de busca que marca como lido
    assert all("PEEK" in c[1] for c in chamadas if c[0] == "fetch")
