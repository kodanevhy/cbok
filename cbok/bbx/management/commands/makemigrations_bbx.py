from django.core.management.base import CommandError
from django.core.management.commands.makemigrations import Command as MakeMigrationsCommand
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.questioner import NonInteractiveMigrationQuestioner


class BbxMigrationQuestioner(NonInteractiveMigrationQuestioner):
    def __init__(self, to_state, **kwargs):
        super().__init__(**kwargs)
        self.to_state = to_state

    def ask_rename(self, model_name, old_name, new_name, field_instance):
        renames = {
            "zsvcompilestate": {("zstack_root", "zsvirt_root")},
            "zsvworktreecontainerstate": {
                ("zstack_root", "zsvirt_root"),
                ("zstack_head", "zsvirt_head"),
            },
        }
        if (old_name, new_name) not in renames.get(model_name, set()):
            return False
        model = self.to_state.models.get(("bbx", model_name))
        return model is not None and model.fields.get(new_name) is field_instance


class BbxMigrationAutodetector(MigrationAutodetector):
    def __init__(self, from_state, to_state, questioner):
        questioner = BbxMigrationQuestioner(
            to_state,
            specified_apps=questioner.specified_apps,
            dry_run=questioner.dry_run,
            verbosity=questioner.verbosity,
            log=questioner.log,
        )
        super().__init__(from_state, to_state, questioner)


class Command(MakeMigrationsCommand):
    help = "Create bbx migrations without prompting, preserving known ZSvirt source fields."
    autodetector = BbxMigrationAutodetector

    def handle(self, *app_labels, **options):
        if app_labels and set(app_labels) != {"bbx"}:
            raise CommandError("makemigrations_bbx only supports the bbx app.")
        options["interactive"] = False
        return super().handle("bbx", **options)
