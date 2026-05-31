"""
medicine_price_services.py
==========================
Fetches live medicine prices from Truemeds, Netmeds, Tata 1mg via AnakinWire.
Uses AnakinWire class directly — single source of truth for API URLs.
"""
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.anakin_wire_services import AnakinWire
from django.conf import settings

logger = logging.getLogger(__name__)

CITY = getattr(settings, "MEDICINE_PRICE_CITY", "New Delhi")


def _wire_run(action_id: str, params: dict) -> dict | None:
    """Submit + poll using AnakinWire — correct URLs guaranteed."""
    try:
        wire = AnakinWire()
        resp = wire.execute(action_id, params)
        job_id = resp.get("job_id")
        if not job_id:
            logger.warning("[wire] %s — no job_id. Response: %s", action_id, resp)
            return None
        logger.debug("[wire] %s submitted → job_id=%s", action_id, job_id)
        result = wire.wait_for_result(job_id)
        if result is None:
            logger.warning("[wire] %s job_id=%s — timed out or failed", action_id, job_id)
        return result
    except Exception as e:
        logger.error("[wire] %s error: %s", action_id, e)
        return None


def _fetch_netmeds(query: str) -> dict:
    result = _wire_run("nm_search", {"query": query, "page_id": "*", "per_page": 10})
    print("\nNETMED RAW RESPONSE")
    print(result)
    if not result:
        return {"source": "Netmeds", "available": False, "products": []}

    data = result.get("data", result)
    if isinstance(data.get("data"), dict):
        data = data["data"]
    raw_products = (
        data.get("products") or data.get("items") or data.get("results") or []
    )
    candidates = []
    for p in raw_products[:10]:
        attrs = p.get("attributes", {})
        # Netmeds wraps prices in nested dicts: p["price"]["effective"]["min"]
        price_obj = p.get("price", {})
        effective = price_obj.get("effective", {})
        marked    = price_obj.get("marked", {})

        # Try nested structure first, then fall back to flat keys
        price = (effective.get("min") or effective.get("max")
                 or p.get("mrp") or p.get("sellingPrice")
                 or p.get("discountedPrice") or p.get("selling_price")
                 or attrs.get("min_effective") or attrs.get("mstar-sellingprice"))
        mrp   = (marked.get("min") or marked.get("max")
                 or p.get("maxRetailPrice") or p.get("max_retail_price")
                 or attrs.get("min_marked") or attrs.get("mrp"))

        if not price:
            continue

        discount_str = p.get("discount", "")  # already a string like "12% OFF"
        slug = p.get("slug") or p.get("urlKey") or p.get("url_key") or str(p.get("uid", ""))

        candidates.append({
            "name":     p.get("name") or p.get("productName") or p.get("title") or attrs.get("mstar-displaynamewops", ""),
            "mrp":      float(mrp) if mrp else None,
            "price":    float(price),
            "discount": discount_str,
            "pack":     p.get("packSize") or p.get("pack_size") or p.get("pack") or attrs.get("mstar-packlabel") or attrs.get("packsize", ""),
            "mfr":      p.get("manufacturer") or p.get("brand") or attrs.get("marketername", ""),
            "url":      f"https://www.netmeds.com/product/{slug}" if slug else "https://www.netmeds.com",
        })
    best = min(candidates, key=lambda x: x["price"]) if candidates else None
    products = [best] if best else []
    logger.info("[wire] netmeds found %d products for '%s'", len(products), query)
    return {"source": "Netmeds", "available": bool(products), "products": products}


def _fetch_1mg(query: str) -> dict:
    result = _wire_run("tmg_search", {"query": query, "city": CITY, "page": 0})
    print("\n1MG RAW RESPONSE")
    print(result)
    if not result:
        return {"source": "Tata 1mg", "available": False, "products": []}

    data = result.get("data", result)
    if isinstance(data.get("data"), dict):
        data = data["data"]
    raw_products = (
        data.get("products") or data.get("skus") or data.get("items")
        or data.get("results") or data.get("search_results") or []
    )
    candidates = []
    for p in raw_products[:10]:
        price_summary = p.get("price_summary", {})
        mrp   = p.get("mrp") or p.get("maxPrice") or p.get("max_price") or price_summary.get("mrp")
        price = p.get("price") or p.get("sellingPrice") or p.get("discountedPrice") or p.get("selling_price") or price_summary.get("discounted_price")
        if not price:
            continue
        discount = p.get("discount") or p.get("discountPercent") or p.get("discount_percent") or price_summary.get("discount_text", "")
        discount_text = discount if isinstance(discount, str) else f"{discount}% off" if discount else ""
        slug     = p.get("url") or p.get("slug") or p.get("urlKey") or p.get("url_key") or p.get("id", "")
        candidates.append({
            "name":     p.get("name") or p.get("productName") or p.get("title", ""),
            "mrp":      float(mrp) if mrp else None,
            "price":    float(price),
            "discount": discount_text,
            "pack":     p.get("packSize") or p.get("packForm") or p.get("pack_size") or p.get("label", ""),
            "mfr":      p.get("manufacturer") or p.get("manufacturerName") or p.get("marketer_name", ""),
            "url":      f"https://www.1mg.com{slug}" if str(slug).startswith("/") else f"https://www.1mg.com/drugs/{slug}" if slug else "https://www.1mg.com",
        })
    best = min(candidates, key=lambda x: x["price"]) if candidates else None
    products = [best] if best else []
    logger.info("[wire] 1mg found %d products for '%s'", len(products), query)
    return {"source": "Tata 1mg", "available": bool(products), "products": products}


class MedicinePriceService:

    def get_prices_for_drug(self, drug_name: str) -> dict:
        query = re.sub(r"\([^)]*\)", "", drug_name)
        query = query.strip()
        start = time.time()
        logger.info("[price] fetching '%s'", query)

        # Run all 3 fetchers in parallel; collect by source name
        SOURCE_NAMES = ["Netmeds", "Tata 1mg"]
        raw_results = {}
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {
                ex.submit(_fetch_netmeds, query):  "Netmeds",
                ex.submit(_fetch_1mg, query):      "Tata 1mg",
            }
            for future in as_completed(futures):
                source_name = futures[future]
                try:
                    raw_results[source_name] = future.result()
                except Exception as e:
                    logger.error("[price] fetcher error for %s: %s", source_name, e)
                    raw_results[source_name] = {"source": source_name, "available": False, "products": []}

        # Guarantee all 3 sources are always present in output
        # Each source has at most 1 product (the cheapest from that source)
        sources = []
        for name in SOURCE_NAMES:
            src = raw_results.get(name, {"source": name, "available": False, "products": []})
            product = src["products"][0] if src["products"] else None
            sources.append({
                "source":    name,
                "available": bool(product),
                "name":      product["name"] if product else None,
                "price":     product["price"] if product else None,
                "mrp":       product["mrp"] if product else None,
                "discount":  product["discount"] if product else None,
                "pack":      product["pack"] if product else None,
                "url":       product["url"] if product else None,
            })

        # Compute cheapest across all available sources
        cheapest = None
        for src in sources:
            if src["available"] and src["price"] is not None:
                if cheapest is None or src["price"] < cheapest["price"]:
                    cheapest = {
                        "source": src["source"],
                        "name":   src["name"],
                        "price":  src["price"],
                        "url":    src["url"],
                    }

        elapsed = round(time.time() - start, 1)
        logger.info("[price] done in %ss — cheapest=₹%s from %s",
                    elapsed,
                    cheapest["price"] if cheapest else "N/A",
                    cheapest["source"] if cheapest else "N/A")

        return {
            "drug_name": drug_name,
            "sources":   sources,
            "cheapest":  cheapest,
            "elapsed_s": elapsed,
        }

    def get_prices_for_prescription(self, drugs: list[dict]) -> list[dict]:
        for drug in drugs:
            query = (
                drug.get("resolved_brand")
                or drug.get("dataset_name")
                or drug.get("matched_name")
                or drug.get("resolved_generic")
                or drug.get("ocr_name")
                or ""
            ).strip()
            if not query:
                drug["prices"] = None
                continue
            if not drug.get("is_verified", False):
                drug["prices"] = {"drug_name": query, "sources": [], "cheapest": None, "skipped": True}
                continue
            drug["prices"] = self.get_prices_for_drug(query)
        return drugs