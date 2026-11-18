def _text_for_anchor(document_text, text_anchor):
    if not text_anchor or not document_text:
        return ""
    pieces = []
    for segment in text_anchor.text_segments:
        start = int(segment.start_index) if segment.start_index else 0
        end = int(segment.end_index)
        pieces.append(document_text[start:end])
    return "".join(pieces).strip()


def _normalized_value(entity):
    normalized = entity.normalized_value
    if not normalized:
        return None
    for attribute in ("text", "money_value", "date_value", "integer_value", "float_value"):
        value = getattr(normalized, attribute, None)
        if value not in (None, ""):
            if attribute == "money_value":
                return {
                    "amount": value.units + value.nanos / 1_000_000_000,
                    "currency": value.currency_code,
                }
            if attribute == "date_value":
                return {
                    "year": value.year,
                    "month": value.month,
                    "day": value.day,
                }
            return value
    return None


def extract_document_data(document):
    text = document.text or ""
    fields = {}
    line_items = []

    for entity in document.entities:
        value = _text_for_anchor(text, entity.text_anchor) or entity.mention_text or ""
        item = {
            "value": _normalized_value(entity) if _normalized_value(entity) is not None else value,
            "raw_value": value,
            "confidence": round(float(entity.confidence), 4),
        }
        if entity.properties:
            child_fields = {}
            for property_entity in entity.properties:
                child_value = (
                    _text_for_anchor(text, property_entity.text_anchor)
                    or property_entity.mention_text
                    or ""
                )
                child_fields[property_entity.type_] = {
                    "value": _normalized_value(property_entity)
                    if _normalized_value(property_entity) is not None
                    else child_value,
                    "raw_value": child_value,
                    "confidence": round(float(property_entity.confidence), 4),
                }
            item["properties"] = child_fields
        if entity.type_.startswith("line_item"):
            line_items.append(item)
        else:
            fields[entity.type_] = item

    return {
        "text": text,
        "fields": fields,
        "line_items": line_items,
        "page_count": len(document.pages),
        "processor": "Google Cloud Document AI Invoice Parser",
    }
