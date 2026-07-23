def import_all_models() -> None:
    from app.db.models import (  # noqa: F401
        catalog,
        conversation,
        knowledge,
        order,
        ticket,
        user,
        warranty,
    )


import_all_models()
