from django.template.loader import render_to_string


def render_email_template(
    template: str,
    context: dict,
) -> str:
    return render_to_string(template, context)
