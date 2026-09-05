from django import forms

from .catalog import POINTS_BY_NAME, suggested_points
from .models import Chore, Status


class ChoreForm(forms.ModelForm):
    class Meta:
        model = Chore
        fields = [
            "name", "category", "assigned_to", "due_at",
            "recurrence", "points", "notes",
        ]
        widgets = {
            "due_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "name": forms.TextInput(attrs={"list": "catalog-names", "autofocus": True}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["assigned_to"].empty_label = "Nobody (shared pool - burns points)"
        # Blank means "price it from the catalog", so it must not come prefilled.
        self.fields["points"].required = False
        if self.instance.pk is None:
            self.fields["points"].initial = None
        # Setting an owner after the fact would leave a burned chore owned, still
        # worth nothing, and no longer reclaimable. Reclaim is the way in.
        if self.instance.status == Status.COMPLETED:
            self.fields["assigned_to"].disabled = True
        self.catalog_names = sorted(POINTS_BY_NAME)

    def clean(self):
        cleaned = super().clean()
        # A standard chore prices itself, but only when the user left it to us.
        if cleaned.get("points") is None:
            cleaned["points"] = suggested_points(cleaned.get("name") or "") or 1
        return cleaned
