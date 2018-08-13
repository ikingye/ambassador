# Copyright 2018 Datawire. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License

import sys

from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple, Union
from typing import cast as typecast

import json
import logging
import os

import jsonschema

from pkg_resources import Requirement, resource_filename

from .utils import RichStatus\
    #, SourcedDict, read_cert_secret, save_cert, TLSPaths, kube_v1, check_cert_file
from .resource import Resource
from .mapping import Mapping

#from .VERSION import Version

#############################################################################
## config.py -- the main configuration parser for Ambassador
##
## Ambassador configures itself by creating a new Config object, which calls
## Config.__init__().
##
## __init__() sets up all the defaults for everything, then walks over all the
## YAML it can find and calls self.load_yaml() to load each YAML file. After
## everything is loaded, it calls self.process_all_objects() to build the
## config objects.
##
## load_yaml() does the heavy lifting around YAML parsing and such, including
## managing K8s annotations if so requested. Every object in every YAML file is
## parsed and saved before any object is processed.
##
## process_all_objects() walks all the saved objects and creates an internal
## representation of the Ambassador config in the data structures initialized
## by __init__(). Each object is processed with self.process_object(). This
## internal representation is called the intermediate config.
##
## process_object() handles a single parsed object from YAML. It uses
## self.validate_object() to make sure of a schema match; assuming that's
## good, most of the heavy lifting is done by a handler method. The handler
## method for a given type is named handle_kind(), with kind in lowercase,
## so e.g. the Mapping object is processed using the handle_mapping() method.
##
## After all of that, the actual Envoy config is generated from the intermediate
## config using generate_envoy_config().
##
## The diag service also uses generate_intermediate_for() to extract the
## intermediate config for a given mapping or service.

# Custom types
# ServiceInfo is a tuple of information about a service: 
# service name, service URL, originate TLS?, TLS context name
ServiceInfo = Tuple[str, str, bool, str]

# StringOrList is either a string or a list of strings.
StringOrList = Union[str, List[str]]


class Config:
    # CLASS VARIABLES
    # When using multiple Ambassadors in one cluster, use AMBASSADOR_ID to distinguish them.
    ambassador_id: ClassVar[str] = os.environ.get('AMBASSADOR_ID', 'default')
    runtime: ClassVar[str] = "kubernetes" if os.environ.get('KUBERNETES_SERVICE_HOST', None) else "docker"
    namespace: ClassVar[str] = os.environ.get('AMBASSADOR_NAMESPACE', 'default')

    # INSTANCE VARIABLES
    current_resource: Optional[Resource] = None

    # XXX flat wrong
    schemas: Dict[str, dict]
    config: Dict[str, Dict[str, Resource]]

    breakers: Dict[str, Resource]
    outliers: Dict[str, Resource]

    # rkey => Resource
    sources: Dict[str, Resource]

    # Allow overriding the location of a resource with a Pragma
    location_overrides: Dict[str, Dict[str, str]]

    # Set up the default probes and such.
    # XXX These should become... Resources?
    default_liveness_probe: Dict[str, Any]
    default_readiness_probe: Dict[str, Any]
    default_diagnostics: Dict[str, Any]

    errors: Dict[str, List[str]]
    fatal_errors: int
    object_errors: int

    def __init__(self, schema_dir_path: Optional[str]=None) -> None:
        if not schema_dir_path:
            # Note that this "resource_filename" has to do with setuptool packages, not
            # with our Resource class.
            schema_dir_path = resource_filename(Requirement.parse("ambassador"), "schemas")

        self.schema_dir_path = schema_dir_path

        self.logger = logging.getLogger("ambassador.config")

        # self.logger.debug("Scout version %s" % Config.scout_version)
        self.logger.debug("Runtime       %s" % Config.runtime)
        self.logger.debug("SCHEMA DIR    %s" % os.path.abspath(self.schema_dir_path))

        self._reset()

    def _reset(self) -> None:
        """
        Resets this Config to the empty, default state so it can load a new config.
        """

        self.logger.debug("RESET")

        self.current_resource = None

        self.schemas = {}
        self.config = {}

        self.breakers = {}
        self.outliers = {}

        self.sources = {}

        self.location_overrides = {}

        # Save our magic internal sources.
        self.save_source(Resource.internal_resource())
        self.save_source(Resource.diagnostics_resource())

        # Set up the default probes and such.
        self.default_liveness_probe = {
            "enabled": True,
            "prefix": "/ambassador/v0/check_alive",
            "rewrite": "/ambassador/v0/check_alive",
            # "service" gets added later
        }

        self.default_readiness_probe = {
            "enabled": True,
            "prefix": "/ambassador/v0/check_ready",
            "rewrite": "/ambassador/v0/check_ready",
            # "service" gets added later
        }

        self.default_diagnostics = {
            "enabled": True,
            "prefix": "/ambassador/v0/",
            "rewrite": "/ambassador/v0/",
            # "service" gets added later
        }

        self.errors = {}
        self.fatal_errors = 0
        self.object_errors = 0

    def __str__(self) -> str:
        s = [ "<Config:" ]

        for kind, configs in self.config.items():
            s.append("  %s:" % kind)

            for rkey, resource in configs.items():
                s.append("    %s" % resource)

        s.append(">")

        return "\n".join(s)

    def dump(self, output=sys.stdout):
        output.write("CONFIG:\n")

        for kind, configs in self.config.items():
            output.write("  %s:\n" % kind)

            for rkey, resource in configs.items():
                output.write("  %s\n" % resource)
                output.write("  %s\n" % repr(resource))

    def save_source(self, resource: Resource) -> None:
        """
        Save a give Resource as a source of Ambassador config information.
        """
        self.sources[resource.rkey] = resource

    def load_all(self, resources: Iterable[Resource]) -> None:
        """
        Loads all of a set of Resources. It is the caller's responsibility to arrange for 
        the set of Resources to be sorted in some way that makes sense.
        """
        for resource in resources:
            # XXX I think this whole override thing should go away.
            #
            # Any override here?
            if resource.rkey in self.location_overrides:
                # Let Pragma objects override source information for this filename.
                override = self.location_overrides[resource.rkey]
                resource.location = override.get('source', resource.rkey)

            # Is an ambassador_id present in this object?
            allowed_ids: StringOrList = resource.get('ambassador_id', 'default')

            if allowed_ids:
                # Make sure it's a list. Yes, this is Draconian,
                # but the jsonschema will allow only a string or a list,
                # and guess what? Strings are Iterables.
                if type(allowed_ids) != list:
                    allowed_ids = typecast(StringOrList, [ allowed_ids ])

                if Config.ambassador_id not in allowed_ids:
                    self.logger.debug("LOAD_ALL: skip %s; id %s not in %s" %
                                      (resource, Config.ambassador_id, allowed_ids))
                    return

            self.logger.debug("LOAD_ALL: %s @ %s" % (resource, resource.location))

            rc = self.process(resource)

            if not rc:
                # Object error. Not good but we'll allow the system to start.
                self.post_error(rc, resource=resource)

        if self.fatal_errors:
            # Kaboom.
            raise Exception("ERROR ERROR ERROR Unparseable configuration; exiting")

        if self.errors:
            self.logger.error("ERROR ERROR ERROR Starting with configuration _errors")

    # def clean_and_copy(self, d):
    #     out = []
    #
    #     for key in sorted(d.keys()):
    #         original = d[key]
    #         copy = dict(**original)
    #
    #         if '_source' in original:
    #             del(original['_source'])
    #
    #         if '_referenced_by' in original:
    #             del(original['_referenced_by'])
    #
    #         out.append(copy)
    #
    #     return out

    def post_error(self, rc: RichStatus, resource=None):
        if not resource:
            resource = self.current_resource

        if not resource:
            raise Exception("FATAL: trying to post an error from a totally unknown resource??")

        self.save_source(resource)
        resource.post_error(rc.toDict())

        # XXX Probably don't need this data structure, since we can walk the source
        # list and get them all.
        errors = self.errors.setdefault(resource.rkey, [])
        errors.append(rc.toDict())
        self.logger.error("%s: %s" % (resource, rc))

    def process(self, resource: Resource) -> RichStatus:
        # This should be impossible.
        if not resource:
            return RichStatus.fromError("undefined object???")

        self.current_resource = resource

        if not resource.apiVersion:
            return RichStatus.fromError("need apiVersion")

        if not resource.kind:
            return RichStatus.fromError("need kind")

        # Is this a pragma object?
        if resource.kind == 'Pragma':
            # Yes. Handle this inline and be done.
            return self.handle_pragma(resource)

        # Not a pragma. It needs a name...
        if 'name' not in resource:
            return RichStatus.fromError("need name")

        # ...and off we go. Save the source info...
        self.save_source(resource)

        # ...and figure out if this thing is OK.
        rc = self.validate_object(resource)

        if not rc:
            # Well that's no good.
            return rc

        # OK, so far so good. Grab the handler for this object type.
        handler_name = "handle_%s" % resource.kind.lower()
        handler = getattr(self, handler_name, None)

        if not handler:
            handler = self.save_object
            self.logger.warning("%s: no handler for %s, just saving" % (resource, resource.kind))
        else:
            self.logger.debug("%s: handling %s..." % (resource, resource.kind))

        try:
            handler(resource)
        except Exception as e:
            # Bzzzt.
            raise
            return RichStatus.fromError("%s: could not process %s object: %s" % (resource, resource.kind, e))

        # OK, all's well.
        self.current_resource = None

        return RichStatus.OK(msg="%s object processed successfully" % resource.kind)

    def validate_object(self, resource: Resource) -> RichStatus:
        # This is basically "impossible"
        if not (("apiVersion" in resource) and ("kind" in resource) and ("name" in resource)):
            return RichStatus.fromError("must have apiVersion, kind, and name")

        apiVersion = resource.apiVersion

        # Ditch the leading ambassador/ that really needs to be there.
        if apiVersion.startswith("ambassador/"):
            apiVersion = apiVersion.split('/')[1]
        else:
            return RichStatus.fromError("apiVersion %s unsupported" % apiVersion)

        # Do we already have this schema loaded?
        schema_key = "%s-%s" % (apiVersion, resource.kind)
        schema = self.schemas.get(schema_key, None)

        if not schema:
            # Not loaded. Go find it on disk.
            schema_path = os.path.join(self.schema_dir_path, apiVersion,
                                       "%s.schema" % resource.kind)

            try:
                # Load it up...
                schema = json.load(open(schema_path, "r"))

                # ...and then cache it, if it exists. Note that we'll never
                # get here if we find something that doesn't parse.
                if schema:
                    self.schemas[schema_key] = typecast(Dict[Any, Any], schema)
            except OSError:
                self.logger.debug("no schema at %s, skipping" % schema_path)
            except json.decoder.JSONDecodeError as e:
                self.logger.warning("corrupt schema at %s, skipping (%s)" %
                                    (schema_path, e))

        if schema:
            # We have a schema. Does the object validate OK?
            try:
                jsonschema.validate(resource.as_dict(), schema)
            except jsonschema.exceptions.ValidationError as e:
                # Nope. Bzzzzt.
                return RichStatus.fromError("not a valid %s: %s" % (resource.kind, e))

        # All good. Return an OK.
        return RichStatus.OK(msg="valid %s" % resource.kind)

    def safe_store(self, storage_name: str, resource: Resource, allow_log: bool=True) -> None:
        """
        Safely store a Resource under a given storage name. The storage_name is separate
        because we may need to e.g. store a Module under the 'ratelimit' name or the like.
        Within a storage_name bucket, the Resource will be stored under its name.

        :param storage_name: where shall we file this?
        :param resource: what shall we file?
        :param allow_log: if True, logs that we're saving this thing.
        """

        storage = self.config.setdefault(storage_name, {})

        if resource.name in storage:
            # Oooops.
            raise Exception("%s defines %s %s, which is already present" %
                            (resource, resource.kind, resource.name))

        if allow_log:
            self.logger.debug("%s: saving %s %s" %
                              (resource, resource.kind, resource.name))

        storage[resource.name] = resource

    def save_object(self, resource: Resource, allow_log: bool=False) -> None:
        """
        Saves a Resource using its kind as the storage class name. Sort of the
        defaulted version of safe_store.

        :param resource: what shall we file?
        :param allow_log: if True, logs that we're saving this thing.
        """

        self.safe_store(resource.kind, resource, allow_log=allow_log)

    def get_config(self, key: str) -> Any:
        return self.config.get(key, None)

    def get_module(self, module_name: str) -> Optional[Resource]:
        """
        Fetch a module from the module store. Can return None if no
        such module exists.

        :param module_name: name of the module you want.
        """

        modules = self.get_config("modules")

        if modules:
            return modules.get(module_name, None)
        else:
            return None

    def module_lookup(self, module_name: str, key: str, default: Any=None) -> Any:
        """
        Look up a specific key in a given module. If the named module doesn't 
        exist, or if the key doesn't exist in the module, return the default.

        :param module_name: name of the module you want.
        :param key: key to look up within the module
        :param default: default value if the module is missing or has no such key
        """

        module = self.get_module(module_name)

        if module:
            return module.get(key, default)

        return default

    def each(self, name) -> Iterator[Resource]:
        return self.config.get(name).__iter__()

    # XXX Misnamed. handle_pragma isn't the same signature as, say, handle_mapping.
    # XXX Is this needed any more??
    def handle_pragma(self, resource: Resource) -> RichStatus:
        """
        Handles a Pragma object. May not be needed any more...
        """

        rkey = resource.rkey

        keylist = sorted([x for x in sorted(resource.keys()) if ((x != 'apiVersion') and (x != 'kind'))])

        self.logger.debug("PRAGMA: %s" % keylist)

        for key in keylist:
            if key == 'source':
                override = self.location_overrides.setdefault(rkey, {})
                override['source'] = resource['source']

                self.logger.debug("PRAGMA: override %s to %s" %
                                  (rkey, self.location_overrides[rkey]['source']))

        return RichStatus.OK(msg="handled pragma object")

    def handle_module(self, resource: Resource) -> None:
        """
        Handles a Module resource.
        """

        # Make a new Resource from the 'config' element of this Resource
        # Note that we leave the original serialization intact, since it will
        # indeed show a human the YAML that defined this module.
        #
        # XXX This should be Module.from_resource()...
        module_resource = Resource.from_resource(resource, kind="Module", **resource.config)

        self.safe_store("modules", module_resource)

    def handle_ratelimitservice(self, resource: Resource) -> None:
        """
        Handles a RateLimitService resource.
        """

        self.safe_store("ratelimit_configs", resource)

    def handle_tracingservice(self, resource: Resource) -> None:
        """
        Handles a TracingService resource.
        """

        self.safe_store("tracing_configs", resource)

    def handle_authservice(self, resource: Resource) -> None:
        """
        Handles an AuthService resource.
        """

        self.safe_store("auth_configs", resource)

    def handle_mapping(self, resource: Mapping) -> None:
        """
        Handles a Mapping resource.

        Mappings are complex things, so a lot of stuff gets buried in a Mapping 
        object.
        """

        self.safe_store("mappings", resource)