# -*- coding: utf-8 -*-
import inspect
import json
import re
from urllib.parse import urljoin

import tornado.template
import tornado.web
from tornado.util import re_unescape
from tornado_swirl.openapi import types

import tornado_swirl.settings as settings

__author__ = 'rduldulao'


def json_dumps(obj, pretty=False):
    return json.dumps(obj, sort_keys=True, indent=4, separators=(',', ': ')) if pretty else json.dumps(obj)


class SwaggerUIHandler(tornado.web.RequestHandler):
    """Serves the Swagger UI"""
    def initialize(self, static_path, **kwds):
        self.static_path = static_path

    def get_template_path(self):
        return self.static_path

    def get(self):
        discovery_url = urljoin(
            self.request.full_url(), self.reverse_url(settings.URL_SWAGGER_API_SPEC))
        self.render('index.html', discovery_url=discovery_url)

# class SwaggerResourcesHandler(tornado.web.RequestHandler):
#     def initialize(self, api_version, exclude_namespaces, **kwds):
#         self.api_version = api_version
#         self.exclude_namespaces = exclude_namespaces

#     def get(self):
#         self.set_header('content-type', 'application/json')
#         u = urlparse(self.request.full_url())
#         resources = {
#             'apiVersion': self.api_version,
#             'openapi': SWAGGER_VERSION,
#             'basePath': '%s://%s' % (u.scheme, u.netloc),
#             'produces': ["application/json"],
#             'description': 'Test Api Spec',
#             'apis': [{
#                 'path': self.reverse_url(URL_SWAGGER_API_SPEC),
#                 'description': 'Test Api Spec'
#             }]
#         }

#         self.finish(json_dumps(resources, self.get_arguments('pretty')))


class SwaggerApiHandler(tornado.web.RequestHandler):
    """Openapi 3.0 spec generator class handler"""

    def get(self):
        """Get handler"""
        self.set_header('content-type', 'application/json')
        apis = self.find_api()  # this is a generator
        servers = []
        server_settings = settings.default_settings.get("servers")
        
        for server in server_settings:
            for key in list(server.keys()):
                if key not in ('url', 'description'):
                    server.pop(key, None)
            if server:
                servers.append(server)
        
        if not servers:
            server_host = self.request.host.split(',')[0]
            servers = [{
                'url': self.request.protocol + "://" + server_host + "/",
                'description': 'Default server'
            }]

        specs = {
            'openapi': settings.SWAGGER_VERSION,
            'info': {
                'title': settings.default_settings.get("title"),
                'description': settings.default_settings.get("description"),
                'version': settings.default_settings.get("api_version"),
            },
            'servers': servers,
            'paths': {path: self.__get_api_spec(spec, operations)
                      for path, spec, operations in apis},
        }

        schemas = settings.get_schemas()
        if schemas:
            specs.update(
                {
                    "components": {
                        "schemas": {
                            name: self.__get_schema_spec(schemaCls)
                            for (name, schemaCls) in schemas.items()
                        }
                    }
                }
            )

        self.finish(json_dumps(specs, self.get_arguments('pretty')))

    def __get_schema_spec(self, cls):
        spec = cls.schema_spec
        props = [(prop.name, self._prop_to_dict(prop), prop.required)
                 for (_, prop) in spec.properties.items()]
        required = [name for name, _, req in props if req]

        val = {"type": "object"}
        if required:
            val.update({"required": required})

        val.update({
            "properties": {
                name: d for name, d, r in props
            }
        })

        return val

    def _prop_to_dict(self, prop):
        schema = self.__get_type(prop)['schema']
        if schema is not None:
            schema.update(prop.kwargs)
        return schema

    def __get_api_spec(self, spec, operations):
        paths = {}
        for api in operations:
            paths[api[0]] = {
                'operationId': str(spec.__name__) + "." + api[0],
                'summary': api[1].summary.strip(),
                'description': api[1].description.strip(),
                'parameters': self.__get_params(api[1]),
            }
            #print("Body Params: ", api[1].body_params)
            if api[1].body_params:
                paths[api[0]]["requestBody"] = self.__get_request_body(api[1])

            paths[api[0]]["responses"] = self.__get_responses(api[1])
        return paths

    def __detect_content_from_type(self, val) -> (str, bool, str):
        if val.type.name == "file":
            return "file", False, val.type.contents
        if val.type.name in settings.get_schemas().keys():
            return val.type.name, True, None

        return val.type.name, False, None

    def __get_params(self, path_spec):
        params = []
        allps = sorted(path_spec.path_params.values(), key=lambda x: x.order) + \
            sorted(path_spec.header_params.values(), key=lambda x: x.order) + \
            sorted(path_spec.query_params.values(), key=lambda x: x.order) + \
            sorted(path_spec.cookie_params.values(),
                   key=lambda x: x.order)  # + \
        # [path_spec.body_param] body param
        for param in allps:
            if param:
                param_data = {
                    "in": param.ptype,
                    "name": param.name,
                    "required": param.required,
                    "description": str(param.description).strip()
                }
                param_data.update(self.__get_type(param))
                params.append(param_data)
        return params

    def __get_request_body(self, path_spec):
        contents = {}
        if path_spec.body_params:
            files_detected = 0  #content = file:xxxx default text/plain
            form_data_detected = 0 #application/x-www-form-urlencoded
            models_detected = 0 #application/json or application/xml

            for (_, val) in path_spec.body_params.items():
                content, ismodel, ftype = self.__detect_content_from_type(val)
                if ftype is not None:
                    files_detected += 1
                elif ismodel:
                    models_detected += 1
                else:
                    form_data_detected += 1

            ctype = ''
            if form_data_detected > 0 and not files_detected and not models_detected:
                ctype = 'application/x-www-form-urlencoded'
                contents[ctype] = {
                    "schema": {
                        "properties": {
                            spec.name: spec.type.schema
                            for spec in path_spec.body_params.values()
                        }
                    }
                }
            elif files_detected == 1 and not form_data_detected and not models_detected:
                entry = list(path_spec.body_params.values())[0]
                contents[entry.type.contents] = {
                    "schema": {
                        "type": "string",
                        "format": "binary"  #TODO: When to use byte/base64?
                    }
                }
            elif (files_detected > 0 and \
                  (form_data_detected > 0 or models_detected > 0)) or \
                  models_detected > 1:
                contents["multipart/form-data"] = {
                    "schema": {
                        "properties": {
                            spec.name: spec.type.schema
                            for spec in path_spec.body_params.values()
                        }
                    }
                }
            elif models_detected == 1 and not files_detected and not form_data_detected:
                params_entry = list(path_spec.body_params.values())[0]
                file_type = 'application/json'
                contents[file_type] = {
                    "schema":  params_entry.type.schema
                }
            else:
                ctype = 'Unknown'

        return {"content": contents}

    def __get_responses(self, path_spec):
        params = {}
        allresps = sorted(path_spec.responses.values(), key=lambda x: x.name)
        for param in allresps:
            if param:
                params[param.name] = {
                    "description": param.description,
                    "content":
                        # should return default produces if none, otherwise detect from type
                        self._detect_content(param)
                }
                # TODO: implement examples
        return params

    def _detect_content(self, param):
        if param.type.name == "None":
            return None

        if param.type.name in ("integer", "number", "string", "boolean"):
            return {
                "text/plain": {
                    "schema": param.type.schema
                }
            }
        return {
            "application/json": {
                    "schema": param.type.schema
                }
            }

    def __get_type(self, param):
        return {"schema": param.type.schema}

    @staticmethod
    def find_api():
        for route_spec in settings.api_routes():
            # TODO decorate  url
            url, _ = _find_groups(route_spec[0])
            path = url
            spec = route_spec[1]
            operations = [(name, member.path_spec) for (
                name, member) in inspect.getmembers(spec) if hasattr(member, 'path_spec')]
            # since these ops have the same path, they should have the same path_params
            # in their path_spec, so get the member with
            # the most path_param and set it on all
            if operations:
                path_param_spec = operations[0][1].path_params
                for (_, path_spec) in operations[1:]:
                    if len(path_spec.path_params) > len(path_param_spec):
                        path_param_spec = path_spec.path_params
                for _, path_sp in operations:
                    path_sp.path_params = path_param_spec
                vals = path_param_spec.values()
                sorted(vals, key=lambda x: x.order)
                path = url % tuple(
                    ['{%s}' % arg for arg in [param.name for param in vals]]
                )

            else:
                continue

            yield path, spec, operations


def _find_groups(url: str):
    """Returns a tuple (reverse string, group count) for a url.

    For example: Given the url pattern /([0-9]{4})/([a-z-]+)/, this method
    would return ('/%s/%s/', 2).
    """
    regex = re.compile(url)
    pattern = url
    if pattern.startswith('^'):
        pattern = pattern[1:]
    if pattern.endswith('$'):
        pattern = pattern[:-1]

    if regex.groups != pattern.count('('):
        # The pattern is too complicated for our simplistic matching,
        # so we can't support reversing it.
        return None, None

    pieces = []
    for fragment in pattern.split('('):
        if ')' in fragment:
            paren_loc = fragment.index(')')
            if paren_loc >= 0:
                pieces.append('%s' + fragment[paren_loc + 1:])
        else:
            try:
                unescaped_fragment = re_unescape(fragment)
            except ValueError:
                # If we can't unescape part of it, we can't
                # reverse this url.
                return (None, None)
            pieces.append(unescaped_fragment)
    return ''.join(pieces), regex.groups
