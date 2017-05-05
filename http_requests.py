import sublime, sublime_plugin

import os
import re
from urllib import parse

import requests
from requests import delete, get, head, options, patch, post, put


class RequestCommandMixin:

    def response_content(self, request, response):
        r = response
        header = '{} {}\n{}s\n{}'.format(
            r.status_code, r.reason, r.elapsed.total_seconds(), r.url
        )
        headers = '\n'.join(
            [ '{}: {}'.format(k, v) for k, v in sorted(r.headers.items()) ]
        )
        content = r.text

        return '\n\n'.join(
            [' '.join(request.split()), header, '[cmd+r] replay request', headers, content]
        )

    def import_variables(self, requests_file_path=None):
        requests_file_path = requests_file_path or self.view.file_name()
        requests_file_dir = os.path.dirname( requests_file_path )

        globals()['env_file'] = self.config.get('env_file') # default `env_file` read from settings
        p = re.compile('\s*env_file\s*=.*') # `env_file` can be overridden from within requests file
        with open(requests_file_path) as f:
            for line in f:
                m = p.match(line)
                if m:
                    exec(line, globals())
                    break # stop looking after first match

        env_file = globals().get('env_file')
        if env_file:
            env_file_path = os.path.join( requests_file_dir, env_file )
            with open(env_file_path) as f:
                exec(f.read(), globals())


class RequestCommand(RequestCommandMixin, sublime_plugin.TextCommand):

    def run(self, edit):
        self.config = sublime.load_settings('http_requests.sublime-settings')
        self.import_variables()
        selections = self.get_selections()
        for selection in selections:
            response = eval(selection)
            self.open_response_view(edit, selection, response)

    def get_selections(self):
        view = self.view
        selections = []
        for region in view.sel():
            if not region.empty():
                selections.append( view.substr(region) )
            else:
                selections.append( view.substr(view.line(region)) )
        return selections

    def open_response_view(self, edit, request, response):
        window = self.view.window()
        view = window.new_file()
        view.set_scratch(True)
        view.settings().set('http_requests.response_view', True)
        view.settings().set('http_requests.requests_file_path', self.view.file_name())
        view.set_name('{}: {}'.format(
            response.request.method, parse.urlparse(response.url).path
        ))
        view.insert(edit, 0, self.response_content(request, response))


class ReplayRequestCommand(sublime_plugin.TextCommand, RequestCommandMixin):

    def run(self, edit):
        self.config = sublime.load_settings('http_requests.sublime-settings')
        self.import_variables( self.view.settings().get('http_requests.requests_file_path') )
        selection = self.get_selection()
        response = eval(selection)
        self.open_response_view(edit, selection, response)

    def get_selection(self):
        return self.view.substr( self.view.line(0) )

    def open_response_view(self, edit, request, response):
        self.view.erase( edit, sublime.Region(0, self.view.size()) )
        self.view.insert(edit, 0, self.response_content(request, response))
