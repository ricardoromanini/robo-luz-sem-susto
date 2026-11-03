"""Shopee Afiliados — Open API (GraphQL): o produto que aparece nos vídeos "Achado".

Assinatura: SHA256(app_id + timestamp + corpo + secret). Chaves SHOPEE_APP_ID / SHOPEE_SECRET.
O link devolvido (offerLink) já é o link de afiliado.
"""
from __future__ import annotations

import hashlib
import json
import time

import requests

from ..config import env

URL = "https://open-api.affiliate.shopee.com.br/graphql"

CONSULTA = """
query($palavra: String, $limite: Int) {
  productOfferV2(keyword: $palavra, sortType: 2, page: 1, limit: $limite) {
    nodes { itemId productName priceMin priceDiscountRate commissionRate sales ratingStar imageUrl offerLink }
  }
}
"""


def ativo() -> bool:
    return bool(env("SHOPEE_APP_ID") and env("SHOPEE_SECRET"))


def buscar(palavra: str, limite: int = 20) -> list[dict]:
    corpo = json.dumps({"query": CONSULTA, "variables": {"palavra": palavra, "limite": limite}}, separators=(",", ":"))
    ts = str(int(time.time()))
    app_id = env("SHOPEE_APP_ID")
    assinatura = hashlib.sha256(f"{app_id}{ts}{corpo}{env('SHOPEE_SECRET')}".encode()).hexdigest()
    r = requests.post(URL, data=corpo, timeout=60, headers={
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={assinatura}"})
    r.raise_for_status()
    resp = r.json()
    if resp.get("errors"):
        raise RuntimeError(f"Shopee recusou: {resp['errors']}")
    return [{"id": str(n["itemId"]), "nome": n["productName"], "preco": float(n["priceMin"]),
             "comissao": float(n.get("commissionRate") or 0), "vendas": int(n.get("sales") or 0),
             "nota": float(n.get("ratingStar") or 0), "imagem": n["imageUrl"], "link": n["offerLink"]}
            for n in resp["data"]["productOfferV2"]["nodes"]]


def melhor_oferta(palavra: str, exigir: list[str] | None = None, nota_minima: float = 4.6,
                  vendas_minimas: int = 100) -> dict | None:
    """O produto mais confiável para mostrar: bem avaliado, muito vendido e que é mesmo o tipo pedido
    (exigir = palavras que precisam estar no nome, para a busca não trazer outra coisa)."""
    exigir = [e.lower() for e in (exigir or [])]
    bons = [o for o in buscar(palavra)
            if o["nota"] >= nota_minima and o["vendas"] >= vendas_minimas
            and all(e in o["nome"].lower() for e in exigir)]
    if not bons:
        return None
    return max(bons, key=lambda o: o["nota"] * 10 + min(o["vendas"], 5000) / 250 + o["comissao"] * 100)
