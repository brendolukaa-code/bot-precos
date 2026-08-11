"""
Busca de preços via Google Shopping (SerpAPI).
Mesmo núcleo da versão anterior, adaptado para retornar resultado
para qualquer usuário/produto.
"""

import os, re, requests

SERPAPI_KEY  = os.environ.get("SERPAPI_KEY")
SERPAPI_URL  = "https://serpapi.com/search"

DOMINIOS_BR  = [".com.br", "mercadolivre.com", "mercadolibre.com"]

TERMOS_PECAS = [
    "escova lateral", "escova principal", "filtro hepa", "filtro lavável",
    "filtro lavavel", "bateria de reposição", "bateria substitut",
    "reservatório de", "pano de limpeza", "refil ", "peça avulsa",
    "kit de acessório", "kit de peça", "kit escova", "kit filtro",
]

TERMOS_USADO = ["usado", "recondicionado", "seminovo", "refurbished"]


def fmt_brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def é_parcela(item: dict) -> bool:
    campos = " ".join([
        item.get("price", ""),
        item.get("snippet", ""),
        " ".join(item.get("extensions", []) or []),
    ]).lower()
    return bool(re.search(r"\dx\s|x\s*r\$|parcela|/mês|por mês|em \d+x", campos))


def preco_realista(preco: float, preco_alvo: float) -> bool:
    if not preco_alvo:
        return True
    return preco >= preco_alvo * 0.50


def é_acessorio(titulo: str) -> bool:
    return any(p in titulo.lower() for p in TERMOS_PECAS)


def é_usado(item: dict) -> bool:
    texto = " ".join([
        item.get("title", ""), item.get("condition", ""), item.get("snippet", ""),
    ]).lower()
    return any(t in texto for t in TERMOS_USADO)


def modelo_no_titulo(titulo: str, modelo: str) -> bool:
    if not modelo:
        return True
    return modelo.lower() in titulo.lower()


def é_dominio_br(link: str) -> bool:
    return any(d in link.lower() for d in DOMINIOS_BR)


def esta_disponivel(oferta: dict) -> bool:
    texto = " ".join([oferta.get("tag", "")] + (oferta.get("details_and_offers") or [])).lower()
    return not any(t in texto for t in ["indispon", "esgotado", "fora de estoque", "out of stock"])


def obter_link_br(page_token, preco_alvo=0):
    if not page_token:
        return None, None, None
    try:
        resp = requests.get(SERPAPI_URL, params={
            "engine": "google_immersive_product", "page_token": page_token,
            "gl": "br", "hl": "pt-br", "api_key": SERPAPI_KEY,
        }, timeout=30)
        resp.raise_for_status()
        ofertas = resp.json().get("product_results", {}).get("stores", [])
        validas = [
            o for o in ofertas
            if o.get("extracted_price") and o.get("link")
            and esta_disponivel(o)
            and é_dominio_br(o["link"])
            and not é_parcela(o)
            and preco_realista(o["extracted_price"], preco_alvo)
        ]
        if not validas:
            return None, None, None
        validas.sort(key=lambda o: o["extracted_price"])
        m = validas[0]
        return m["link"], m.get("name"), m["extracted_price"]
    except Exception:
        return None, None, None


def buscar_mais_barato(termo: str, modelo: str = "", preco_alvo: float = 0):
    if not SERPAPI_KEY:
        raise RuntimeError("SERPAPI_KEY não definida")

    resp = requests.get(SERPAPI_URL, params={
        "engine": "google_shopping", "q": termo,
        "gl": "br", "hl": "pt-br", "api_key": SERPAPI_KEY,
    }, timeout=60)
    resp.raise_for_status()
    resultados = resp.json().get("shopping_results", [])

    def aceitar(r, checar_modelo):
        preco = r.get("extracted_price", 0)
        return (
            preco
            and not é_parcela(r)
            and not é_usado(r)
            and not é_acessorio(r.get("title", ""))
            and preco_realista(preco, preco_alvo)
            and (not checar_modelo or modelo_no_titulo(r.get("title", ""), modelo))
        )

    itens = [r for r in resultados if aceitar(r, True)]
    if not itens and modelo:
        itens = [r for r in resultados if aceitar(r, False)]

    if not itens:
        return None

    itens.sort(key=lambda r: r["extracted_price"])

    for candidato in itens[:10]:
        link, loja, preco = obter_link_br(
            candidato.get("immersive_product_page_token"), preco_alvo
        )
        if link:
            preco_final = preco or candidato["extracted_price"]
            cupom = None
            for ext in (candidato.get("extensions") or []):
                if re.search(r"cupom|coupon|código|promo", ext, re.IGNORECASE):
                    cupom = ext
                    break
            return {
                "titulo":    candidato.get("title"),
                "preco":     preco_final,
                "preco_txt": fmt_brl(preco_final),
                "loja":      loja or candidato.get("source", "—"),
                "link":      link,
                "foto":      candidato.get("thumbnail"),
                "cupom":     cupom,
            }

    c = itens[0]
    return {
        "titulo":    c.get("title"),
        "preco":     c["extracted_price"],
        "preco_txt": c.get("price") or fmt_brl(c["extracted_price"]),
        "loja":      c.get("source", "—"),
        "link":      c.get("product_link") or c.get("link"),
        "foto":      c.get("thumbnail"),
        "cupom":     None,
    }
