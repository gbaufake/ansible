# -*- coding: utf-8 -*-
#
# (c) 2015, René Moser <mail@renemoser.net>
#
# This code is part of Ansible, but is an independent component.
# This particular file snippet, and this file snippet only, is BSD licensed.
# Modules you write using this snippet, which is embedded dynamically by Ansible
# still belong to the author of the module, and may assign their own license
# to the complete work.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#    * Redistributions of source code must retain the above copyright
#      notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright notice,
#      this list of conditions and the following disclaimer in the documentation
#      and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
# USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
import sys
import time

from ansible.module_utils._text import to_text

try:
    from cs import CloudStack, CloudStackException, read_config
    HAS_LIB_CS = True
except ImportError:
    HAS_LIB_CS = False

CS_HYPERVISORS = [
    'KVM', 'kvm',
    'VMware', 'vmware',
    'BareMetal', 'baremetal',
    'XenServer', 'xenserver',
    'LXC', 'lxc',
    'HyperV', 'hyperv',
    'UCS', 'ucs',
    'OVM', 'ovm',
    'Simulator', 'simulator',
]

if sys.version_info > (3,):
    long = int


def cs_argument_spec():
    return dict(
        api_key=dict(default=os.environ.get('CLOUDSTACK_KEY')),
        api_secret=dict(default=os.environ.get('CLOUDSTACK_SECRET'), no_log=True),
        api_url=dict(default=os.environ.get('CLOUDSTACK_ENDPOINT')),
        api_http_method=dict(choices=['get', 'post'], default=os.environ.get('CLOUDSTACK_METHOD') or 'get'),
        api_timeout=dict(type='int', default=os.environ.get('CLOUDSTACK_TIMEOUT') or 10),
        api_region=dict(default=os.environ.get('CLOUDSTACK_REGION') or 'cloudstack'),
    )


def cs_required_together():
    return [['api_key', 'api_secret']]


class AnsibleCloudStack(object):

    def __init__(self, module):
        if not HAS_LIB_CS:
            module.fail_json(msg="python library cs required: pip install cs")

        self.result = {
            'changed': False,
            'diff': {
                'before': dict(),
                'after': dict()
            }
        }

        # Common returns, will be merged with self.returns
        # search_for_key: replace_with_key
        self.common_returns = {
            'id': 'id',
            'name': 'name',
            'created': 'created',
            'zonename': 'zone',
            'state': 'state',
            'project': 'project',
            'account': 'account',
            'domain': 'domain',
            'displaytext': 'display_text',
            'displayname': 'display_name',
            'description': 'description',
        }

        # Init returns dict for use in subclasses
        self.returns = {}
        # these values will be casted to int
        self.returns_to_int = {}
        # these keys will be compared case sensitive in self.has_changed()
        self.case_sensitive_keys = [
            'id',
            'displaytext',
            'displayname',
            'description',
        ]

        self.module = module
        self._connect()

        # Helper for VPCs
        self._vpc_networks_ids = None

        self.domain = None
        self.account = None
        self.project = None
        self.ip_address = None
        self.network = None
        self.vpc = None
        self.zone = None
        self.vm = None
        self.vm_default_nic = None
        self.os_type = None
        self.hypervisor = None
        self.capabilities = None
        self.network_acl = None

    def _connect(self):
        api_region = self.module.params.get('api_region') or os.environ.get('CLOUDSTACK_REGION')
        try:
            config = read_config(api_region)
        except KeyError:
            config = {}

        api_config = {
            'endpoint': self.module.params.get('api_url') or config.get('endpoint'),
            'key': self.module.params.get('api_key') or config.get('key'),
            'secret': self.module.params.get('api_secret') or config.get('secret'),
            'timeout': self.module.params.get('api_timeout') or config.get('timeout'),
            'method': self.module.params.get('api_http_method') or config.get('method'),
        }
        self.result.update({
            'api_region': api_region,
            'api_url': api_config['endpoint'],
            'api_key': api_config['key'],
            'api_timeout': api_config['timeout'],
            'api_http_method': api_config['method'],
        })
        if not all([api_config['endpoint'], api_config['key'], api_config['secret']]):
            self.fail_json(msg="Missing api credentials: can not authenticate")
        self.cs = CloudStack(**api_config)

    def fail_json(self, **kwargs):
        self.result.update(kwargs)
        self.module.fail_json(**self.result)

    def get_or_fallback(self, key=None, fallback_key=None):
        value = self.module.params.get(key)
        if not value:
            value = self.module.params.get(fallback_key)
        return value

    def has_changed(self, want_dict, current_dict, only_keys=None):
        result = False
        for key, value in want_dict.items():

            # Optionally limit by a list of keys
            if only_keys and key not in only_keys:
                continue

            # Skip None values
            if value is None:
                continue

            if key in current_dict:
                if isinstance(value, (int, float, long, complex)):
                    # ensure we compare the same type
                    if isinstance(value, int):
                        current_dict[key] = int(current_dict[key])
                    elif isinstance(value, float):
                        current_dict[key] = float(current_dict[key])
                    elif isinstance(value, long):
                        current_dict[key] = long(current_dict[key])
                    elif isinstance(value, complex):
                        current_dict[key] = complex(current_dict[key])

                    if value != current_dict[key]:
                        self.result['diff']['before'][key] = current_dict[key]
                        self.result['diff']['after'][key] = value
                        result = True
                else:
                    before_value = to_text(current_dict[key])
                    after_value = to_text(value)

                    if self.case_sensitive_keys and key in self.case_sensitive_keys:
                        if before_value != after_value:
                            self.result['diff']['before'][key] = before_value
                            self.result['diff']['after'][key] = after_value
                            result = True

                    # Test for diff in case insensitive way
                    elif before_value.lower() != after_value.lower():
                        self.result['diff']['before'][key] = before_value
                        self.result['diff']['after'][key] = after_value
                        result = True
            else:
                self.result['diff']['before'][key] = None
                self.result['diff']['after'][key] = to_text(value)
                result = True
        return result

    def _get_by_key(self, key=None, my_dict=None):
        if my_dict is None:
            my_dict = {}
        if key:
            if key in my_dict:
                return my_dict[key]
            self.fail_json(msg="Something went wrong: %s not found" % key)
        return my_dict

    def get_network_acl(self, key=None):
        if self.network_acl is None:
            args = {
                'name': self.module.params.get('network_acl'),
                'vpcid': self.get_vpc(key='id'),
            }
            network_acls = self.cs.listNetworkACLLists(**args)
            if network_acls:
                self.network_acl = network_acls['networkacllist'][0]
                self.result['network_acl'] = self.network_acl['name']
        if self.network_acl:
            return self._get_by_key(key, self.network_acl)
        else:
            self.fail_json("Network ACL %s not found" % self.module.params.get('network_acl'))

    def get_vpc(self, key=None):
        """Return a VPC dictionary or the value of given key of."""
        if self.vpc:
            return self._get_by_key(key, self.vpc)

        vpc = self.module.params.get('vpc')
        if not vpc:
            vpc = os.environ.get('CLOUDSTACK_VPC')
        if not vpc:
            return None

        args = {
            'account': self.get_account(key='name'),
            'domainid': self.get_domain(key='id'),
            'projectid': self.get_project(key='id'),
            'zoneid': self.get_zone(key='id'),
        }
        vpcs = self.cs.listVPCs(**args)
        if not vpcs:
            self.fail_json(msg="No VPCs available.")

        for v in vpcs['vpc']:
            if vpc in [v['name'], v['displaytext'], v['id']]:
                # Fail if the identifyer matches more than one VPC
                if self.vpc:
                    self.fail_json(msg="More than one VPC found with the provided identifyer '%s'" % vpc)
                else:
                    self.vpc = v
                    self.result['vpc'] = v['name']
        if self.vpc:
            return self._get_by_key(key, self.vpc)
        self.fail_json(msg="VPC '%s' not found" % vpc)

    def is_vpc_network(self, network_id):
        """Returns True if network is in VPC."""
        # This is an efficient way to query a lot of networks at a time
        if self._vpc_networks_ids is None:
            args = {
                'account': self.get_account(key='name'),
                'domainid': self.get_domain(key='id'),
                'projectid': self.get_project(key='id'),
                'zoneid': self.get_zone(key='id'),
            }
            vpcs = self.cs.listVPCs(**args)
            self._vpc_networks_ids = []
            if vpcs:
                for vpc in vpcs['vpc']:
                    for n in vpc.get('network', []):
                        self._vpc_networks_ids.append(n['id'])
        return network_id in self._vpc_networks_ids

    def get_network(self, key=None):
        """Return a network dictionary or the value of given key of."""
        if self.network:
            return self._get_by_key(key, self.network)

        network = self.module.params.get('network')
        if not network:
            vpc_name = self.get_vpc(key='name')
            if vpc_name:
                self.fail_json(msg="Could not find network for VPC '%s' due missing argument: network" % vpc_name)
            return None

        args = {
            'account': self.get_account(key='name'),
            'domainid': self.get_domain(key='id'),
            'projectid': self.get_project(key='id'),
            'zoneid': self.get_zone(key='id'),
            'vpcid': self.get_vpc(key='id')
        }
        networks = self.cs.listNetworks(**args)
        if not networks:
            self.fail_json(msg="No networks available.")

        for n in networks['network']:
            # ignore any VPC network if vpc param is not given
            if 'vpcid' in n and not self.get_vpc(key='id'):
                continue
            if network in [n['displaytext'], n['name'], n['id']]:
                self.result['network'] = n['name']
                self.network = n
                return self._get_by_key(key, self.network)
        self.fail_json(msg="Network '%s' not found" % network)

    def get_project(self, key=None):
        if self.project:
            return self._get_by_key(key, self.project)

        project = self.module.params.get('project')
        if not project:
            project = os.environ.get('CLOUDSTACK_PROJECT')
        if not project:
            return None
        args = {
            'account': self.get_account(key='name'),
            'domainid': self.get_domain(key='id')
        }
        projects = self.cs.listProjects(**args)
        if projects:
            for p in projects['project']:
                if project.lower() in [p['name'].lower(), p['id']]:
                    self.result['project'] = p['name']
                    self.project = p
                    return self._get_by_key(key, self.project)
        self.fail_json(msg="project '%s' not found" % project)

    def get_ip_address(self, key=None):
        if self.ip_address:
            return self._get_by_key(key, self.ip_address)

        ip_address = self.module.params.get('ip_address')
        if not ip_address:
            self.fail_json(msg="IP address param 'ip_address' is required")

        args = {
            'ipaddress': ip_address,
            'account': self.get_account(key='name'),
            'domainid': self.get_domain(key='id'),
            'projectid': self.get_project(key='id'),
            'vpcid': self.get_vpc(key='id'),
        }
        ip_addresses = self.cs.listPublicIpAddresses(**args)

        if not ip_addresses:
            self.fail_json(msg="IP address '%s' not found" % args['ipaddress'])

        self.ip_address = ip_addresses['publicipaddress'][0]
        return self._get_by_key(key, self.ip_address)

    def get_vm_guest_ip(self):
        vm_guest_ip = self.module.params.get('vm_guest_ip')
        default_nic = self.get_vm_default_nic()

        if not vm_guest_ip:
            return default_nic['ipaddress']

        for secondary_ip in default_nic['secondaryip']:
            if vm_guest_ip == secondary_ip['ipaddress']:
                return vm_guest_ip
        self.fail_json(msg="Secondary IP '%s' not assigned to VM" % vm_guest_ip)

    def get_vm_default_nic(self):
        if self.vm_default_nic:
            return self.vm_default_nic

        nics = self.cs.listNics(virtualmachineid=self.get_vm(key='id'))
        if nics:
            for n in nics['nic']:
                if n['isdefault']:
                    self.vm_default_nic = n
                    return self.vm_default_nic
        self.fail_json(msg="No default IP address of VM '%s' found" % self.module.params.get('vm'))

    def get_vm(self, key=None):
        if self.vm:
            return self._get_by_key(key, self.vm)

        vm = self.module.params.get('vm')
        if not vm:
            self.fail_json(msg="Virtual machine param 'vm' is required")

        args = {
            'account': self.get_account(key='name'),
            'domainid': self.get_domain(key='id'),
            'projectid': self.get_project(key='id'),
            'zoneid': self.get_zone(key='id'),
            'networkid': self.get_network(key='id'),
        }
        vms = self.cs.listVirtualMachines(**args)
        if vms:
            for v in vms['virtualmachine']:
                if vm.lower() in [v['name'].lower(), v['displayname'].lower(), v['id']]:
                    self.vm = v
                    return self._get_by_key(key, self.vm)
        self.fail_json(msg="Virtual machine '%s' not found" % vm)

    def get_zone(self, key=None):
        if self.zone:
            return self._get_by_key(key, self.zone)

        zone = self.module.params.get('zone')
        if not zone:
            zone = os.environ.get('CLOUDSTACK_ZONE')
        zones = self.cs.listZones()

        if not zones:
            self.fail_json(msg="No zones available. Please create a zone first")

        # use the first zone if no zone param given
        if not zone:
            self.zone = zones['zone'][0]
            return self._get_by_key(key, self.zone)

        if zones:
            for z in zones['zone']:
                if zone.lower() in [z['name'].lower(), z['id']]:
                    self.result['zone'] = z['name']
                    self.zone = z
                    return self._get_by_key(key, self.zone)
        self.fail_json(msg="zone '%s' not found" % zone)

    def get_os_type(self, key=None):
        if self.os_type:
            return self._get_by_key(key, self.zone)

        os_type = self.module.params.get('os_type')
        if not os_type:
            return None

        os_types = self.cs.listOsTypes()
        if os_types:
            for o in os_types['ostype']:
                if os_type in [o['description'], o['id']]:
                    self.os_type = o
                    return self._get_by_key(key, self.os_type)
        self.fail_json(msg="OS type '%s' not found" % os_type)

    def get_hypervisor(self):
        if self.hypervisor:
            return self.hypervisor

        hypervisor = self.module.params.get('hypervisor')
        hypervisors = self.cs.listHypervisors()

        # use the first hypervisor if no hypervisor param given
        if not hypervisor:
            self.hypervisor = hypervisors['hypervisor'][0]['name']
            return self.hypervisor

        for h in hypervisors['hypervisor']:
            if hypervisor.lower() == h['name'].lower():
                self.hypervisor = h['name']
                return self.hypervisor
        self.fail_json(msg="Hypervisor '%s' not found" % hypervisor)

    def get_account(self, key=None):
        if self.account:
            return self._get_by_key(key, self.account)

        account = self.module.params.get('account')
        if not account:
            account = os.environ.get('CLOUDSTACK_ACCOUNT')
        if not account:
            return None

        domain = self.module.params.get('domain')
        if not domain:
            self.fail_json(msg="Account must be specified with Domain")

        args = {
            'name': account,
            'domainid': self.get_domain(key='id'),
            'listall': True
        }
        accounts = self.cs.listAccounts(**args)
        if accounts:
            self.account = accounts['account'][0]
            self.result['account'] = self.account['name']
            return self._get_by_key(key, self.account)
        self.fail_json(msg="Account '%s' not found" % account)

    def get_domain(self, key=None):
        if self.domain:
            return self._get_by_key(key, self.domain)

        domain = self.module.params.get('domain')
        if not domain:
            domain = os.environ.get('CLOUDSTACK_DOMAIN')
        if not domain:
            return None

        args = {
            'listall': True,
        }
        domains = self.cs.listDomains(**args)
        if domains:
            for d in domains['domain']:
                if d['path'].lower() in [domain.lower(), "root/" + domain.lower(), "root" + domain.lower()]:
                    self.domain = d
                    self.result['domain'] = d['path']
                    return self._get_by_key(key, self.domain)
        self.fail_json(msg="Domain '%s' not found" % domain)

    def query_tags(self, resource, resource_type):
        args = {
            'resourceids': resource['id'],
            'resourcetype': resource_type,
        }
        tags = self.cs.listTags(**args)
        return self.get_tags(resource=tags, key='tag')

    def get_tags(self, resource=None, key='tags'):
        existing_tags = []
        for tag in resource.get(key) or []:
            existing_tags.append({'key': tag['key'], 'value': tag['value']})
        return existing_tags

    def _process_tags(self, resource, resource_type, tags, operation="create"):
        if tags:
            self.result['changed'] = True
            if not self.module.check_mode:
                args = {
                    'resourceids': resource['id'],
                    'resourcetype': resource_type,
                    'tags': tags,
                }
                if operation == "create":
                    response = self.cs.createTags(**args)
                else:
                    response = self.cs.deleteTags(**args)
                self.poll_job(response)

    def _tags_that_should_exist_or_be_updated(self, resource, tags):
        existing_tags = self.get_tags(resource)
        return [tag for tag in tags if tag not in existing_tags]

    def _tags_that_should_not_exist(self, resource, tags):
        existing_tags = self.get_tags(resource)
        return [tag for tag in existing_tags if tag not in tags]

    def ensure_tags(self, resource, resource_type=None):
        if not resource_type or not resource:
            self.fail_json(msg="Error: Missing resource or resource_type for tags.")

        if 'tags' in resource:
            tags = self.module.params.get('tags')
            if tags is not None:
                self._process_tags(resource, resource_type, self._tags_that_should_not_exist(resource, tags), operation="delete")
                self._process_tags(resource, resource_type, self._tags_that_should_exist_or_be_updated(resource, tags))
                resource['tags'] = self.query_tags(resource=resource, resource_type=resource_type)
        return resource

    def get_capabilities(self, key=None):
        if self.capabilities:
            return self._get_by_key(key, self.capabilities)
        capabilities = self.cs.listCapabilities()
        self.capabilities = capabilities['capability']
        return self._get_by_key(key, self.capabilities)

    def poll_job(self, job=None, key=None):
        if 'jobid' in job:
            while True:
                res = self.cs.queryAsyncJobResult(jobid=job['jobid'])
                if res['jobstatus'] != 0 and 'jobresult' in res:
                    if 'errortext' in res['jobresult']:
                        self.fail_json(msg="Failed: '%s'" % res['jobresult']['errortext'])
                    if key and key in res['jobresult']:
                        job = res['jobresult'][key]
                    break
                time.sleep(2)
        return job

    def get_result(self, resource):
        if resource:
            returns = self.common_returns.copy()
            returns.update(self.returns)
            for search_key, return_key in returns.items():
                if search_key in resource:
                    self.result[return_key] = resource[search_key]

            # Bad bad API does not always return int when it should.
            for search_key, return_key in self.returns_to_int.items():
                if search_key in resource:
                    self.result[return_key] = int(resource[search_key])

            if 'tags' in resource:
                self.result['tags'] = resource['tags']
        return self.result
