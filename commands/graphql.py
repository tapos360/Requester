import sublime
import sublime_plugin

import re
import sys
import traceback
from threading import Thread

import requests

from ..core import RequestCommandMixin
from ..core.parsers import parse_requests
from ..core.responses import prepare_request


placeholder = '__introspection_placeholder'
introspection_query = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      ...FullType
    }
  }
}

fragment FullType on __Type {
  kind
  name
  description
  fields(includeDeprecated: true) {
    name
    description
    args {
      ...InputValue
    }
    type {
      ...TypeRef
    }
    isDeprecated
  }
}

fragment InputValue on __InputValue {
  name
  type { ...TypeRef }
  defaultValue
}

fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
              }
            }
          }
        }
      }
    }
  }
}
"""


def set_graphql_on_view(view, req):
    """If request was to a GraphQL endpoint, send introspection query on a separate
    thread, parse response and set it on view.
    """
    if not req.skwargs.get('gql'):
        return

    def _set(view, url):
        """Ensure types and fields within types can be looked up quickly by name.

        `types` dict has the following format:
            typeName -> typeDict
        Within `typeDict`, `fields` dict has similar format:
            fieldName -> fieldDict
        """
        kwargs = dict(req.kwargs)
        kwargs.pop('params', None)
        kwargs.pop('json', None)
        kwargs['timeout'] = 3
        response = requests.get(url, params={'query': introspection_query}, **kwargs)

        schema = response.json()['data']['__schema']  # get root `Query` type
        query_type = schema['queryType']['name']

        types = {}
        for t in schema['types']:
            types[t['name']] = t
            fields = {f['name']: f for f in (t['fields'] or [])}
            t['fields'] = fields

        view.settings().set('requester.gql_schema', (query_type, types))

    thread = Thread(target=lambda: _set(view, req.url.split('?')[0]))
    thread.start()


class RequesterGqlAutocompleteListener(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        """Runs on all views, but is NOOP unless gql schema has been cached on
        view. Inside gql query string, only completions returned by this method
        are shown.
        """
        schema = view.settings().get('requester.gql_schema', None)
        if not schema:
            return None

        content = view.substr(sublime.Region(0, view.size()))
        m = re.search(r'\bgql\s*=\s*("|\')+', content)
        if m is None:
            return None

        offset, idx = m.end(), view.sel()[0].begin()

        try:
            request = parse_requests(content, n=1)[0]

            if getattr(view, '_env', None) is None:
                view._env = RequestCommandMixin.get_env_dict_from_string(
                   view.settings().get('requester.env_string', None)
                )
            req = prepare_request(request, view._env, 1)
            gql = req.skwargs['gql']
            completions = get_completions(gql, idx-offset, schema)
            return completions
        except:
            print('GraphQL Error:')
            traceback.print_exc(file=sys.stdout)
            return None


def get_completions(gql, idx, schema):
    """Creates AST from `gql` query string, finds out exactly where cursor is in
    string, and uses `schema` to get appropriate completions. Deson't protect
    against exceptions. They should be handled by calling code.
    """
    try:  # at module import time this package is not available
        from graphql.parser import GraphQLParser
    except ImportError:
        print('Install graphql-py with pip for GraphQL autocomplete')
        return None

    start, end = slurp_word(gql, idx)
    gql_parser = GraphQLParser()
    ast = gql_parser.parse(gql[:start] + placeholder + gql[end:])

    for query in ast.definitions:  # get path if it exists
        path = placeholder_path(query, placeholder)
        if path is not None:
            break

    query_type, types = schema
    t = resolve_type(path, types, query_type)
    fields = types[t]['fields']
    completions = [f['name'] for f in fields.values()]
    return (
        zip(completions, completions),
        sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS
    )


def resolve_type(path, types, query_type):
    """Moves back and forth between field names in `path` and GraphQL types to
    find type name of leaf node in path.
    """
    t = query_type
    for f in path[:-1]:  # stop before reaching placeholder
        field = types[t]['fields'][f]
        t = field['type']['name']
    return t


def placeholder_path(field, placeholder):
    """Not the most elegant implementation of DFS. It searches the whole tree and
    keeps track of the path to each node. If it finds `placeholder`, it saves this
    path and returns it after search is finished.
    """
    path = None

    def get_path(selection, placeholder, seen=tuple()):
        for sel in selection.selections:
            seen_next = seen + (sel.name,)
            if sel.name == placeholder:
                nonlocal path
                path = seen_next
            get_path(sel, placeholder, seen_next)

    get_path(field, placeholder)
    return path


def slurp_word(s, idx):
    """Returns index boundaries of word adjacent to `idx` in `s`.
    """
    alnum = r'[A-Za-z0-9_]'
    start, end = idx, idx

    while True:
        if re.match(alnum, s[start-1]):
            start -= 1
        else:
            break
    end = idx
    while True:
        if re.match(alnum, s[end]):
            end += 1
        else:
            break

    return start, end