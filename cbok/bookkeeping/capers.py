from cbok.objects import caper as caper_obj


def get(caper_uuid):
    return caper_obj.Caper.get_by_uuid(caper_uuid)


def create(create_kwargs):
    kwargs = create_kwargs
    caper = caper_obj.Caper(kwargs)
    caper.create()
