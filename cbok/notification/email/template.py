from django.template import loader


def render_email_template(
    template: str,
    context: dict,
) -> str:
    return loader.render_to_string(template, context)
