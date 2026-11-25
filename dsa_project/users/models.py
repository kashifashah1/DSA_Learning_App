"""Custom User model: students log in with their e-mail address."""

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Creates users. E-mails are always stored in lower case."""

    def create_user(self, email, name, password=None, **extra_fields):
        if not email:
            raise ValueError("E-mail is required.")
        if not name:
            raise ValueError("Name is required.")
        user = self.model(email=email.strip().lower(), name=name.strip(), **extra_fields)
        user.set_password(password)  # hashes the password (never stored as plain text)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, name, password=None, **extra_fields):
        extra_fields["is_staff"] = True
        return self.create_user(email, name, password, **extra_fields)


class User(AbstractBaseUser):
    """Table users_user. 'password' and 'last_login' come from AbstractBaseUser."""

    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)  # the login field
    is_staff = models.BooleanField(default=False)  # staff = can use admin functions
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]  # asked by `createsuperuser` besides e-mail and password

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        # Keep e-mails in lower case so "A@x.com" and "a@x.com" are the same account.
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    # Admin functions are for staff only.
    def has_perm(self, perm, obj=None):
        return self.is_active and self.is_staff

    def has_module_perms(self, app_label):
        return self.is_active and self.is_staff
