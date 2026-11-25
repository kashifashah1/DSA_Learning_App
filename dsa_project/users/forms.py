"""Forms for registration, login and profile. All checks are done on the server."""

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError

from .models import User

# One Tailwind style for every input box, so all forms look the same.
INPUT_CLASS = (
    "mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm "
    "focus:border-electric focus:outline-none focus:ring-2 focus:ring-electric"
)


class StyledFormMixin:
    """Adds the Tailwind class to every field of a form."""

    def style_fields(self):
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASS


def clean_unique_email(raw_email, exclude_pk=None):
    """Return the e-mail in lower case, or raise an error if another account has it."""
    email = raw_email.strip().lower()
    taken = User.objects.filter(email__iexact=email)
    if exclude_pk is not None:
        taken = taken.exclude(pk=exclude_pk)
    if taken.exists():
        raise ValidationError("This e-mail is already registered.")
    return email


class RegistrationForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label="Name", max_length=100)
    email = forms.EmailField(label="E-mail", error_messages={"invalid": "Enter a valid e-mail address."})
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise ValidationError("This field is required.")
        return name

    def clean_email(self):
        return clean_unique_email(self.cleaned_data["email"])

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The two passwords do not match.")
        elif password1:
            # Django's password validators (length, common, numeric, similar to e-mail/name).
            temp_user = User(name=cleaned.get("name", ""), email=cleaned.get("email", ""))
            try:
                password_validation.validate_password(password1, temp_user)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned

    def save(self):
        return User.objects.create_user(
            email=self.cleaned_data["email"],
            name=self.cleaned_data["name"],
            password=self.cleaned_data["password1"],
        )


class EmailLoginForm(StyledFormMixin, AuthenticationForm):
    """Login with e-mail + password. A wrong combination gives ONE general error."""

    error_messages = {
        "invalid_login": "The e-mail or password is incorrect.",
        "inactive": "The e-mail or password is incorrect.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "E-mail"
        self.fields["username"].widget.attrs["autocomplete"] = "email"
        self.fields["password"].widget.attrs["autocomplete"] = "current-password"
        self.style_fields()

    def clean_username(self):
        # E-mails are stored in lower case, so "A@x.com" can log in too.
        return self.cleaned_data["username"].strip().lower()


class ProfileForm(StyledFormMixin, forms.Form):
    """Lets a student change only their own name and e-mail."""

    name = forms.CharField(label="Name", max_length=100)
    email = forms.EmailField(label="E-mail", error_messages={"invalid": "Enter a valid e-mail address."})

    def __init__(self, *args, user, **kwargs):
        self.user = user
        kwargs.setdefault("initial", {"name": user.name, "email": user.email})
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise ValidationError("This field is required.")
        return name

    def clean_email(self):
        return clean_unique_email(self.cleaned_data["email"], exclude_pk=self.user.pk)

    def save(self):
        self.user.name = self.cleaned_data["name"]
        self.user.email = self.cleaned_data["email"]
        self.user.save(update_fields=["name", "email"])
        return self.user


class StyledPasswordResetForm(StyledFormMixin, PasswordResetForm):
    """Asks for the e-mail address. It never says whether that address has an account."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "E-mail"
        self.fields["email"].error_messages["invalid"] = "Enter a valid e-mail address."
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.style_fields()


class StyledSetPasswordForm(StyledFormMixin, SetPasswordForm):
    """Chooses the new password (checked by Django's password validators)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "New password"
        self.fields["new_password2"].label = "Confirm new password"
        self.style_fields()
