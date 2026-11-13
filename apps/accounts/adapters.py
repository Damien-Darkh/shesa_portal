"""django-allauth hooks: who may sign in, and how their local record is filled."""
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.http import HttpResponseRedirect

from .models import User


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        # Accounts only come from the identity provider, never local sign-up.
        return False


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        # First SSO login creates the local record (the IdP is the gate).
        return True

    def pre_social_login(self, request, sociallogin):
        user = sociallogin.user
        if user.pk and user.disabled:
            raise ImmediateHttpResponse(HttpResponseRedirect("/account_disabled.html"))
        if user.pk:
            # Fill names/subject the IdP knows but we don't yet. Never overwrite edits.
            data = sociallogin.account.extra_data or {}
            changed = []
            if not user.oidc_subject and sociallogin.account.uid:
                user.oidc_subject = sociallogin.account.uid  # links rows imported from the legacy DB
                changed.append("oidc_subject")
            if not user.first_name and data.get("given_name"):
                user.first_name = data["given_name"]
                changed.append("first_name")
            if not user.last_name and data.get("family_name"):
                user.last_name = data["family_name"]
                changed.append("last_name")
            if not user.authentik_username and data.get("preferred_username"):
                user.authentik_username = data["preferred_username"]  # so delete/disable find this account
                changed.append("authentik_username")
            if changed:
                user.save(update_fields=changed)

    def save_user(self, request, sociallogin, form=None):
        # The very first user ever becomes admin (initial portal setup), as before.
        is_first_ever_user = not User.objects.exists()
        user = super().save_user(request, sociallogin, form)
        if is_first_ever_user:
            user.is_admin = True
            user.save(update_fields=["is_admin"])
        update = []
        if not user.oidc_subject:
            user.oidc_subject = sociallogin.account.uid
            update.append("oidc_subject")
        preferred = (sociallogin.account.extra_data or {}).get("preferred_username")
        if not user.authentik_username and preferred:
            user.authentik_username = preferred
            update.append("authentik_username")
        if update:
            user.save(update_fields=update)
        return user
