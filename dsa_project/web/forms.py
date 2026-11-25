from django import forms

from problems.models import Problem, Subtopic, Topic
from users.forms import INPUT_CLASS


class ProblemFilterForm(forms.Form):
    """Filters of the problem list. All three are optional and checked on the server."""

    topic = forms.ModelChoiceField(
        label="Topic", queryset=Topic.objects.all(), required=False, empty_label="All topics"
    )
    subtopic = forms.ModelChoiceField(
        label="Subtopic",
        queryset=Subtopic.objects.select_related("topic"),
        required=False,
        empty_label="All subtopics",
    )
    difficulty = forms.ChoiceField(
        label="Difficulty",
        choices=[("", "All difficulties")] + Problem.Difficulty.choices,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASS

    def clean(self):
        cleaned = super().clean()
        topic, subtopic = cleaned.get("topic"), cleaned.get("subtopic")
        if topic and subtopic and subtopic.topic_id != topic.pk:
            self.add_error("subtopic", "This subtopic does not belong to the selected topic.")
        return cleaned
