from __future__ import unicode_literals
import re
import sys
from textwrap import TextWrapper

from django.conf import settings
from django.contrib.sites.models import Site
from django.template.loader import render_to_string
from django.utils.encoding import force_unicode
from django.utils.translation import ugettext, ugettext_lazy as _

from mxweb.libs.email import send_email_alternative

# make use of a favourite notifier app such as django-notification
# but if not installed or not desired, fallback will be to do basic emailing
name = getattr(settings, 'POSTMAN_NOTIFIER_APP', 'notification')
if name and name in settings.INSTALLED_APPS:
    name = name + '.models'
    __import__(name)
    notification = sys.modules[name]
else:
    notification = None

# give priority to a favourite mailer app such as django-mailer
# but if not installed or not desired, fallback to django.core.mail
name = getattr(settings, 'POSTMAN_MAILER_APP', 'mailer')
if name and name in settings.INSTALLED_APPS:
    send_mail = __import__(name, globals(), locals(), [str('send_mail')]).send_mail
else:
    from django.core.mail import send_mail

# to disable email notification to users
DISABLE_USER_EMAILING = getattr(settings, 'POSTMAN_DISABLE_USER_EMAILING', False)

# default wrap width; referenced in forms.py
WRAP_WIDTH = 55


def format_body(sender, body, indent=_("> "), width=WRAP_WIDTH):
    """
    Wrap the text and prepend lines with a prefix.

    The aim is to get lines with at most `width` chars.
    But does not wrap if the line is already prefixed.

    Prepends each line with a localized prefix, even empty lines.
    Existing line breaks are preserved.
    Used for quoting messages in replies.

    """
    indent = force_unicode(indent)  # join() doesn't work on lists with lazy translation objects
    wrapper = TextWrapper(width=width, initial_indent=indent, subsequent_indent=indent)
    # rem: TextWrapper doesn't add the indent on an empty text
    quote = '\n'.join([line.startswith(indent) and indent+line or wrapper.fill(line) or indent for line in body.splitlines()])
    return ugettext("\n\n{sender} wrote:\n{body}\n").format(sender=sender, body=quote)


def format_subject(subject):
    """
    Prepend a pattern to the subject, unless already there.

    Matching is case-insensitive.

    """
    str = ugettext("Re: {subject}")
    pattern = '^' + str.replace('{subject}', '.*') + '$'
    return subject if re.match(pattern, subject, re.IGNORECASE) else str.format(subject=subject)


def email(subject_template, text_template, html_template, recipient_list, object, action=None):
    """Compose and send an email."""
    site = Site.objects.get_current()
    ctx_dict = {'site': site, 'object': object, 'action': action}
    subject = render_to_string(subject_template, ctx_dict)
    # Email subject *must not* contain newlines
    subject = ''.join(subject.splitlines())
    message = render_to_string(text_template, ctx_dict)
    utm_campaign = "message_%s" % object.id
    html_dict = {'host_url': settings.MX_WEB_URL,
                 'static_url_fixed': settings.STATIC_URL_FIXED,
                 'subject': subject,
                 'object': object,
                 'action': action,
                 'utm_campaign': utm_campaign,
                 }
    html = render_to_string(html_template, html_dict)
    # during the development phase, consider using the setting: EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    # send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=True)
    send_email_alternative(recipient_list,
                           subject,
                           message, sender=settings.EMAIL_NOTIFICATIONS_ADDRESS, html=html)


def email_visitor(object, action):
    """Email a visitor."""
    email('postman/email_visitor_subject.txt',
          'postman/email_visitor.txt',
          'postman/email_visitor.html',
          [object.email], object, action)


def notify_user(object, action):
    """Notify a user."""
    if action == 'rejection':
        user = object.sender
        label = 'postman_rejection'
    elif action == 'acceptance':
        user = object.recipient
        parent = object.parent
        label = 'postman_reply' if (parent and parent.sender_id == object.recipient_id) else 'postman_message'
    else:
        return
    if notification:
        # the context key 'message' is already used in django-notification/models.py/send_now() (v0.2.0)
        notification.send(users=[user], label=label, extra_context={'pm_message': object, 'pm_action': action})
    else:
        if not DISABLE_USER_EMAILING and user.email and user.is_active and user.get_profile().receive_message_notifications:
            email('postman/email_user_subject.txt', 'postman/email_user.txt', 'postman/email_user.html', [user.email], object, action)


# JSON datetime encoder
import json
import datetime


class DateTimeJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        else:
            return super(DateTimeJSONEncoder, self).default(obj)
