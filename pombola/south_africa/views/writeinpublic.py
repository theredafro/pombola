from django.views.generic.edit import FormView
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404
from django.http import HttpResponseRedirect, HttpResponseServerError
from django.core.urlresolvers import reverse

from pombola.writeinpublic.forms import MessageForm
from pombola.core.models import Person
from pombola.writeinpublic.client import WriteInPublic


class SAWriteToRepresentative(FormView):
    template_name = "writeinpublic/person-write.html"
    form_class = MessageForm

    def get_context_data(self, **kwargs):
        context = super(SAWriteToRepresentative, self).get_context_data(**kwargs)
        person_slug = self.kwargs['person_slug']
        person = get_object_or_404(Person, slug=person_slug)
        context['object'] = person
        return context

    def form_valid(self, form):
        # FIXME: These values should come from config
        person_slug = self.kwargs['person_slug']
        person = get_object_or_404(Person, slug=person_slug)
        client = WriteInPublic("http://10.11.12.13.xip.io:8000", "admin", "123abc")
        response = client.create_message(
            author_name=form.cleaned_data['author_name'],
            author_email=form.cleaned_data['author_email'],
            subject=form.cleaned_data['subject'],
            content=form.cleaned_data['content'],
            # FIXME: This shouldn't be hard-coded
            writeitinstance="/api/v1/instance/3/",
            persons=["https://raw.githubusercontent.com/everypolitician/everypolitician-data/master/data/South_Africa/Assembly/ep-popolo-v1.0.json#person-{uuid}".format(uuid=person.everypolitician_uuid)],
        )
        if response.ok:
            message_id = response.json()['id']
            return HttpResponseRedirect(reverse('sa-writeinpublic-message', kwargs={'message_id': message_id}))
        else:
            # FIXME: This should do something more intelligent
            return HttpResponseServerError()


class SAWriteInPublicMessage(TemplateView):
    template_name = 'writeinpublic/message.html'

    def get_context_data(self, **kwargs):
        context = super(SAWriteInPublicMessage, self).get_context_data(**kwargs)
        client = WriteInPublic("http://10.11.12.13.xip.io:8000", "admin", "123abc")
        context['message'] = client.get_message(self.kwargs['message_id'])
        return context


class SAWriteToRepresentativeMessages(TemplateView):
    template_name = 'writeinpublic/messages.html'

    def get_context_data(self, **kwargs):
        context = super(SAWriteToRepresentativeMessages, self).get_context_data(**kwargs)
        client = WriteInPublic("http://10.11.12.13.xip.io:8000", "admin", "123abc")
        person_slug = self.kwargs['person_slug']
        person = get_object_or_404(Person, slug=person_slug)
        context['person'] = person
        context['messages'] = client.get_messages(person.everypolitician_uuid)
        return context