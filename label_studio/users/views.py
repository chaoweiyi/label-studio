"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.
"""
import logging

import drf_yasg.openapi as openapi
from core.feature_flags import flag_set
from core.middleware import enforce_csrf_checks
from core.permissions import all_permissions, admin_required
from core.utils.common import load_func
from django.conf import settings
from django.contrib import auth
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render, reverse
from django.utils.http import is_safe_url
from drf_yasg.utils import swagger_auto_schema
from organizations.forms import OrganizationSignupForm
from organizations.models import Organization
from rest_framework import status, views
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from users import forms
from users.functions import login, proceed_registration
from users.models import User
from django.utils.decorators import method_decorator

HasObjectPermission = load_func(settings.USER_PERM)

logger = logging.getLogger()


@login_required
def logout(request):
    auth.logout(request)
    if settings.HOSTNAME:
        redirect_url = settings.HOSTNAME
        if not redirect_url.endswith('/'):
            redirect_url += '/'
        return redirect(redirect_url)
    return redirect('/')


@enforce_csrf_checks
def user_signup(request):
    """Sign up page"""
    user = request.user
    next_page = request.GET.get('next')
    token = request.GET.get('token')

    # checks if the URL is a safe redirection.
    if not next_page or not is_safe_url(url=next_page, allowed_hosts=request.get_host()):
        next_page = reverse('projects:project-index')

    user_form = forms.UserSignupForm()
    organization_form = OrganizationSignupForm()

    if user.is_authenticated:
        return redirect(next_page)

    # make a new user
    '''if request.method == 'POST':
        organization = Organization.objects.first()
        if settings.DISABLE_SIGNUP_WITHOUT_LINK is True:
            if not (token and organization and token == organization.token):
                raise PermissionDenied()
        else:
            if token and organization and token != organization.token:
                raise PermissionDenied()

        user_form = forms.UserSignupForm(request.POST)
        organization_form = OrganizationSignupForm(request.POST)

        if user_form.is_valid():
            redirect_response = proceed_registration(request, user_form, organization_form, next_page)
            if redirect_response:
                return redirect_response'''

    if flag_set('fflag_feat_front_lsdv_e_297_increase_oss_to_enterprise_adoption_short'):
        return render(
            request,
            'users/new-ui/user_signup.html',
            {
                'user_form': user_form,
                'organization_form': organization_form,
                'next': next_page,
                'token': token,
            },
        )

    return render(
        request,
        'users/user_signup.html',
        {
            'user_form': user_form,
            'organization_form': organization_form,
            'next': next_page,
            'token': token,
        },
    )


@enforce_csrf_checks
def user_login(request):
    """Login page"""
    user = request.user
    next_page = request.GET.get('next')

    # checks if the URL is a safe redirection.
    if not next_page or not is_safe_url(url=next_page, allowed_hosts=request.get_host()):
        next_page = reverse('projects:project-index')

    login_form = load_func(settings.USER_LOGIN_FORM)
    form = login_form()

    if user.is_authenticated:
        return redirect(next_page)

    if request.method == 'POST':
        form = login_form(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user']
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            if form.cleaned_data['persist_session'] is not True:
                # Set the session to expire when the browser is closed
                request.session['keep_me_logged_in'] = False
                request.session.set_expiry(0)

            # user is organization member
            org_pk = Organization.find_by_user(user).pk
            user.active_organization_id = org_pk
            user.save(update_fields=['active_organization'])
            return redirect(next_page)

    if flag_set('fflag_feat_front_lsdv_e_297_increase_oss_to_enterprise_adoption_short'):
        return render(request, 'users/new-ui/user_login.html', {'form': form, 'next': next_page})

    return render(request, 'users/user_login.html', {'form': form, 'next': next_page})


@login_required
def user_account(request):
    user = request.user

    if user.active_organization is None and 'organization_pk' not in request.session:
        return redirect(reverse('main'))

    form = forms.UserProfileForm(instance=user)
    token = Token.objects.get(user=user)

    if request.method == 'POST':
        form = forms.UserProfileForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            return redirect(reverse('user-account'))

    return render(
        request,
        'users/user_account.html',
        {'settings': settings, 'user': user, 'user_profile_form': form, 'token': token},
    )


@method_decorator(
    name='delete',
    decorator=admin_required
)
class UserSoftDeleteView(views.APIView):
    permission_classes = (IsAuthenticated, HasObjectPermission)
    permission_required = all_permissions.organizations_change

    @swagger_auto_schema(
        tags=['Users'],
        operation_summary='Soft delete user',
        operation_description="""
            Soft delete a specific user in the system by marking them as deleted, 
            without actually removing the user data from the database.
        """,
        manual_parameters=[
            openapi.Parameter(name='pk', type=openapi.TYPE_INTEGER, in_=openapi.IN_PATH, description='User ID'),
        ],
    )
    def delete(self, request, pk, *args, **kwargs):
        try:
            # only fetch & delete user if they are in the same organization as the calling user
            user = User.objects.filter(active_organization=request.user.active_organization).get(pk=pk)
        except User.DoesNotExist:
            raise Http404('User could not be found in organization')

        self.check_object_permissions(request, user)
        if pk == request.user.pk:
            return Response({'detail': 'User cannot delete self'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

        user.soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
