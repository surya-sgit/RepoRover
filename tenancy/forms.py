from django import forms

from .models import RepoSettings, OrganizationConfig

class OrganizationConfigForm(forms.ModelForm):
    # Overwrite fields with explicit password text masking for keys
    llm_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "Leave blank to keep existing key"}),
        label="LLM API Key"
    )
    e2b_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "Leave blank to keep existing key"}),
        label="E2B Sandbox API Key"
    )

    class Meta:
        model = OrganizationConfig
        fields = ["llm_provider", "llm_model_name", "llm_base_url"]
        labels = {
            "llm_provider": "LLM Provider",
            "llm_model_name": "Target Model Name",
            "llm_base_url": "Base URL (Optional)",
        }
        widgets = {
            "llm_provider": forms.Select(attrs={"style": "width: 100%; padding: 8px;"}),
            "llm_model_name": forms.TextInput(attrs={"style": "width: 100%; padding: 8px;", "placeholder": "e.g., gpt-4o, llama3-70b-8192"}),
            "llm_base_url": forms.TextInput(attrs={"style": "width: 100%; padding: 8px;", "placeholder": "e.g., http://localhost:11434/v1"}),
        }

class ByokKeyForm(forms.Form):
    """Submit BYOK secrets. Values are encrypted before storage; never rendered back."""

    gemini_api_key = forms.CharField(
        label="Google Gemini API Key",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave blank to keep the existing key.",
    )
    e2b_api_key = forms.CharField(
        label="E2B API Key",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave blank to keep the existing key.",
    )


class RepoSettingsForm(forms.ModelForm):
    ignored_directories_text = forms.CharField(
        label="Ignored directories (one per line)",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        help_text="Globs skipped during AST parsing, e.g. tests/*",
    )

    class Meta:
        model = RepoSettings
        fields = ["repository_name", "max_concurrency"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["ignored_directories_text"].initial = "\n".join(
                self.instance.ignored_directories or []
            )

    def clean(self):
        cleaned = super().clean()
        raw = cleaned.get("ignored_directories_text", "")
        cleaned["ignored_directories"] = [
            line.strip() for line in raw.splitlines() if line.strip()
        ]
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.ignored_directories = self.cleaned_data.get("ignored_directories", [])
        if commit:
            obj.save()
        return obj
