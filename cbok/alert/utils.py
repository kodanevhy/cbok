from datetime import datetime


def match_question(questions, text):
    for qst in questions:
        if qst.summary and qst.summary in text:
            return qst
    return None


def parse_publish_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None
