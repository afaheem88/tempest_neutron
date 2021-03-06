# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import itertools

import netaddr
import testtools

from tempest.api.network import base
from tempest.common import custom_matchers
from tempest.common.utils import data_utils
from tempest import config
from tempest import exceptions
from tempest import test

CONF = config.CONF


class NetworksTestJSON(base.BaseNetworkTest):
    _interface = 'json'

    """
    Tests the following operations in the Neutron API using the REST client for
    Neutron:

        create a network for a tenant
        list tenant's networks
        show a tenant network details
        create a subnet for a tenant
        list tenant's subnets
        show a tenant subnet details
        network update
        subnet update
        delete a network also deletes its subnets
        list external networks

        All subnet tests are run once with ipv4 and once with ipv6.

    v2.0 of the Neutron API is assumed. It is also assumed that the following
    options are defined in the [network] section of etc/tempest.conf:

        tenant_network_cidr with a block of cidr's from which smaller blocks
        can be allocated for tenant ipv4 subnets

        tenant_network_v6_cidr is the equivalent for ipv6 subnets

        tenant_network_mask_bits with the mask bits to be used to partition the
        block defined by tenant_network_cidr

        tenant_network_v6_mask_bits is the equivalent for ipv6 subnets
    """

    @classmethod
    def resource_setup(cls):
        super(NetworksTestJSON, cls).resource_setup()
        cls.network = cls.create_network()
        cls.name = cls.network['name']
        cls.subnet = cls._create_subnet_with_last_subnet_block(cls.network,
                                                               cls._ip_version)
        cls.cidr = cls.subnet['cidr']
        cls._subnet_data = {6: {'gateway':
                                str(cls._get_gateway_from_tempest_conf(6)),
                                'allocation_pools':
                                cls._get_allocation_pools_from_gateway(6),
                                'dns_nameservers': ['2001:4860:4860::8844',
                                                    '2001:4860:4860::8888'],
                                'host_routes': [{'destination': '2001::/64',
                                                 'nexthop': '2003::1'}],
                                'new_host_routes': [{'destination':
                                                     '2001::/64',
                                                     'nexthop': '2005::1'}],
                                'new_dns_nameservers':
                                ['2001:4860:4860::7744',
                                 '2001:4860:4860::7888']},
                            4: {'gateway':
                                str(cls._get_gateway_from_tempest_conf(4)),
                                'allocation_pools':
                                cls._get_allocation_pools_from_gateway(4),
                                'dns_nameservers': ['8.8.4.4', '8.8.8.8'],
                                'host_routes': [{'destination': '10.20.0.0/32',
                                                 'nexthop': '10.100.1.1'}],
                                'new_host_routes': [{'destination':
                                                     '10.20.0.0/32',
                                                     'nexthop':
                                                     '10.100.1.2'}],
                                'new_dns_nameservers': ['7.8.8.8', '7.8.4.4']}}

    @classmethod
    def _create_subnet_with_last_subnet_block(cls, network, ip_version):
        """Derive last subnet CIDR block from tenant CIDR and
           create the subnet with that derived CIDR
        """
        if ip_version == 4:
            cidr = netaddr.IPNetwork(CONF.network.tenant_network_cidr)
            mask_bits = CONF.network.tenant_network_mask_bits
        elif ip_version == 6:
            cidr = netaddr.IPNetwork(CONF.network.tenant_network_v6_cidr)
            mask_bits = CONF.network.tenant_network_v6_mask_bits

        subnet_cidr = list(cidr.subnet(mask_bits))[-1]
        gateway_ip = str(netaddr.IPAddress(subnet_cidr) + 1)
        return cls.create_subnet(network, gateway=gateway_ip,
                                 cidr=subnet_cidr, mask_bits=mask_bits)

    @classmethod
    def _get_gateway_from_tempest_conf(cls, ip_version):
        """Return first subnet gateway for configured CIDR """
        if ip_version == 4:
            cidr = netaddr.IPNetwork(CONF.network.tenant_network_cidr)
            mask_bits = CONF.network.tenant_network_mask_bits
        elif ip_version == 6:
            cidr = netaddr.IPNetwork(CONF.network.tenant_network_v6_cidr)
            mask_bits = CONF.network.tenant_network_v6_mask_bits

        if mask_bits >= cidr.prefixlen:
            return netaddr.IPAddress(cidr) + 1
        else:
            for subnet in cidr.subnet(mask_bits):
                return netaddr.IPAddress(subnet) + 1

    @classmethod
    def _get_allocation_pools_from_gateway(cls, ip_version):
        """Return allocation range for subnet of given gateway"""
        gateway = cls._get_gateway_from_tempest_conf(ip_version)
        return [{'start': str(gateway + 2), 'end': str(gateway + 3)}]

    def subnet_dict(self, include_keys):
        """Return a subnet dict which has include_keys and their corresponding
           value from self._subnet_data
        """
        return dict((key, self._subnet_data[self._ip_version][key])
                    for key in include_keys)

    def _compare_resource_attrs(self, actual, expected):
        exclude_keys = set(actual).symmetric_difference(expected)
        self.assertThat(actual, custom_matchers.MatchesDictExceptForKeys(
                        expected, exclude_keys))

    def _delete_network(self, network):
        # Deleting network also deletes its subnets if exists
        self.client.delete_network(network['id'])
        if network in self.networks:
            self.networks.remove(network)
        for subnet in self.subnets:
            if subnet['network_id'] == network['id']:
                self.subnets.remove(subnet)

    def _create_verify_delete_subnet(self, cidr=None, mask_bits=None,
                                     **kwargs):
        network = self.create_network()
        net_id = network['id']
        gateway = kwargs.pop('gateway', None)
        subnet = self.create_subnet(network, gateway, cidr, mask_bits,
                                    **kwargs)
        compare_args_full = dict(gateway_ip=gateway, cidr=cidr,
                                 mask_bits=mask_bits, **kwargs)
        compare_args = dict((k, v) for k, v in compare_args_full.iteritems()
                            if v is not None)

        if 'dns_nameservers' in set(subnet).intersection(compare_args):
            self.assertEqual(sorted(compare_args['dns_nameservers']),
                             sorted(subnet['dns_nameservers']))
            del subnet['dns_nameservers'], compare_args['dns_nameservers']

        self._compare_resource_attrs(subnet, compare_args)
        self.client.delete_network(net_id)
        self.networks.pop()
        self.subnets.pop()

    @test.attr(type='smoke')
    def test_create_update_delete_network_subnet(self):
        # Create a network
        name = data_utils.rand_name('network-')
        network = self.create_network(network_name=name)
        self.addCleanup(self._delete_network, network)
        net_id = network['id']
        self.assertEqual('ACTIVE', network['status'])
        # Verify network update
        new_name = "New_network"
        body = self.client.update_network(net_id, name=new_name)
        updated_net = body['network']
        self.assertEqual(updated_net['name'], new_name)
        # Find a cidr that is not in use yet and create a subnet with it
        subnet = self.create_subnet(network)
        subnet_id = subnet['id']
        # Verify subnet update
        new_name = "New_subnet"
        body = self.client.update_subnet(subnet_id, name=new_name)
        updated_subnet = body['subnet']
        self.assertEqual(updated_subnet['name'], new_name)

    @test.attr(type='smoke')
    def test_show_network(self):
        # Verify the details of a network
        body = self.client.show_network(self.network['id'])
        network = body['network']
        for key in ['id', 'name']:
            self.assertEqual(network[key], self.network[key])

    @test.attr(type='smoke')
    def test_show_network_fields(self):
        # Verify specific fields of a network
        fields = ['id', 'name']
        body = self.client.show_network(self.network['id'],
                                        fields=fields)
        network = body['network']
        self.assertEqual(sorted(network.keys()), sorted(fields))
        for field_name in fields:
            self.assertEqual(network[field_name], self.network[field_name])

    @test.attr(type='smoke')
    def test_list_networks(self):
        # Verify the network exists in the list of all networks
        body = self.client.list_networks()
        networks = [network['id'] for network in body['networks']
                    if network['id'] == self.network['id']]
        self.assertNotEmpty(networks, "Created network not found in the list")

    @test.attr(type='smoke')
    def test_list_networks_fields(self):
        # Verify specific fields of the networks
        fields = ['id', 'name']
        body = self.client.list_networks(fields=fields)
        networks = body['networks']
        self.assertNotEmpty(networks, "Network list returned is empty")
        for network in networks:
            self.assertEqual(sorted(network.keys()), sorted(fields))

    @test.attr(type='smoke')
    def test_show_subnet(self):
        # Verify the details of a subnet
        body = self.client.show_subnet(self.subnet['id'])
        subnet = body['subnet']
        self.assertNotEmpty(subnet, "Subnet returned has no fields")
        for key in ['id', 'cidr']:
            self.assertIn(key, subnet)
            self.assertEqual(subnet[key], self.subnet[key])

    @test.attr(type='smoke')
    def test_show_subnet_fields(self):
        # Verify specific fields of a subnet
        fields = ['id', 'network_id']
        body = self.client.show_subnet(self.subnet['id'],
                                       fields=fields)
        subnet = body['subnet']
        self.assertEqual(sorted(subnet.keys()), sorted(fields))
        for field_name in fields:
            self.assertEqual(subnet[field_name], self.subnet[field_name])

    @test.attr(type='smoke')
    def test_list_subnets(self):
        # Verify the subnet exists in the list of all subnets
        body = self.client.list_subnets()
        subnets = [subnet['id'] for subnet in body['subnets']
                   if subnet['id'] == self.subnet['id']]
        self.assertNotEmpty(subnets, "Created subnet not found in the list")

    @test.attr(type='smoke')
    def test_list_subnets_fields(self):
        # Verify specific fields of subnets
        fields = ['id', 'network_id']
        body = self.client.list_subnets(fields=fields)
        subnets = body['subnets']
        self.assertNotEmpty(subnets, "Subnet list returned is empty")
        for subnet in subnets:
            self.assertEqual(sorted(subnet.keys()), sorted(fields))

    def _try_delete_network(self, net_id):
        # delete network, if it exists
        try:
            self.client.delete_network(net_id)
        # if network is not found, this means it was deleted in the test
        except exceptions.NotFound:
            pass

    @test.attr(type='smoke')
    def test_delete_network_with_subnet(self):
        # Creates a network
        name = data_utils.rand_name('network-')
        body = self.client.create_network(name=name)
        network = body['network']
        net_id = network['id']
        self.addCleanup(self._try_delete_network, net_id)

        # Find a cidr that is not in use yet and create a subnet with it
        subnet = self.create_subnet(network)
        subnet_id = subnet['id']

        # Delete network while the subnet still exists
        body = self.client.delete_network(net_id)

        # Verify that the subnet got automatically deleted.
        self.assertRaises(exceptions.NotFound, self.client.show_subnet,
                          subnet_id)

        # Since create_subnet adds the subnet to the delete list, and it is
        # is actually deleted here - this will create and issue, hence remove
        # it from the list.
        self.subnets.pop()

    @test.attr(type='smoke')
    def test_create_delete_subnet_without_gateway(self):
        self._create_verify_delete_subnet()

    @test.attr(type='smoke')
    def test_create_delete_subnet_with_gw(self):
        self._create_verify_delete_subnet(
            **self.subnet_dict(['gateway']))

    @test.attr(type='smoke')
    def test_create_delete_subnet_with_allocation_pools(self):
        self._create_verify_delete_subnet(
            **self.subnet_dict(['allocation_pools']))

    @test.attr(type='smoke')
    def test_create_delete_subnet_with_gw_and_allocation_pools(self):
        self._create_verify_delete_subnet(**self.subnet_dict(
            ['gateway', 'allocation_pools']))

    @test.attr(type='smoke')
    def test_create_delete_subnet_with_host_routes_and_dns_nameservers(self):
        self._create_verify_delete_subnet(
            **self.subnet_dict(['host_routes', 'dns_nameservers']))

    @test.attr(type='smoke')
    def test_create_delete_subnet_with_dhcp_enabled(self):
        self._create_verify_delete_subnet(enable_dhcp=True)

    @test.attr(type='smoke')
    def test_update_subnet_gw_dns_host_routes_dhcp(self):
        network = self.create_network()
        self.addCleanup(self._delete_network, network)

        subnet = self.create_subnet(
            network, **self.subnet_dict(['gateway', 'host_routes',
                                        'dns_nameservers',
                                         'allocation_pools']))
        subnet_id = subnet['id']
        new_gateway = str(netaddr.IPAddress(
                          self._subnet_data[self._ip_version]['gateway']) + 1)
        # Verify subnet update
        new_host_routes = self._subnet_data[self._ip_version][
            'new_host_routes']

        new_dns_nameservers = self._subnet_data[self._ip_version][
            'new_dns_nameservers']
        kwargs = {'host_routes': new_host_routes,
                  'dns_nameservers': new_dns_nameservers,
                  'gateway_ip': new_gateway, 'enable_dhcp': True}

        new_name = "New_subnet"
        body = self.client.update_subnet(subnet_id, name=new_name,
                                         **kwargs)
        updated_subnet = body['subnet']
        kwargs['name'] = new_name
        self.assertEqual(sorted(updated_subnet['dns_nameservers']),
                         sorted(kwargs['dns_nameservers']))
        del subnet['dns_nameservers'], kwargs['dns_nameservers']

        self._compare_resource_attrs(updated_subnet, kwargs)

    @test.attr(type='smoke')
    def test_create_delete_subnet_all_attributes(self):
        self._create_verify_delete_subnet(
            enable_dhcp=True,
            **self.subnet_dict(['gateway', 'host_routes', 'dns_nameservers']))

    @test.attr(type='smoke')
    def test_external_network_visibility(self):
        """Verifies user can see external networks but not subnets."""
        body = self.client.list_networks(**{'router:external': True})
        networks = [network['id'] for network in body['networks']]
        self.assertNotEmpty(networks, "No external networks found")

        nonexternal = [net for net in body['networks'] if
                       not net['router:external']]
        self.assertEmpty(nonexternal, "Found non-external networks"
                                      " in filtered list (%s)." % nonexternal)
        self.assertIn(CONF.network.public_network_id, networks)

        subnets_iter = (network['subnets'] for network in body['networks'])
        # subnets_iter is a list (iterator) of lists. This flattens it to a
        # list of UUIDs
        public_subnets_iter = itertools.chain(*subnets_iter)
        body = self.client.list_subnets()
        subnets = [sub['id'] for sub in body['subnets']
                   if sub['id'] in public_subnets_iter]
        self.assertEmpty(subnets, "Public subnets visible")


class BulkNetworkOpsTestJSON(base.BaseNetworkTest):
    _interface = 'json'

    """
    Tests the following operations in the Neutron API using the REST client for
    Neutron:

        bulk network creation
        bulk subnet creation
        bulk port creation
        list tenant's networks

    v2.0 of the Neutron API is assumed. It is also assumed that the following
    options are defined in the [network] section of etc/tempest.conf:

        tenant_network_cidr with a block of cidr's from which smaller blocks
        can be allocated for tenant networks

        tenant_network_mask_bits with the mask bits to be used to partition the
        block defined by tenant-network_cidr
    """

    def _delete_networks(self, created_networks):
        for n in created_networks:
            self.client.delete_network(n['id'])
        # Asserting that the networks are not found in the list after deletion
        body = self.client.list_networks()
        networks_list = [network['id'] for network in body['networks']]
        for n in created_networks:
            self.assertNotIn(n['id'], networks_list)

    def _delete_subnets(self, created_subnets):
        for n in created_subnets:
            self.client.delete_subnet(n['id'])
        # Asserting that the subnets are not found in the list after deletion
        body = self.client.list_subnets()
        subnets_list = [subnet['id'] for subnet in body['subnets']]
        for n in created_subnets:
            self.assertNotIn(n['id'], subnets_list)

    def _delete_ports(self, created_ports):
        for n in created_ports:
            self.client.delete_port(n['id'])
        # Asserting that the ports are not found in the list after deletion
        body = self.client.list_ports()
        ports_list = [port['id'] for port in body['ports']]
        for n in created_ports:
            self.assertNotIn(n['id'], ports_list)

    @test.attr(type='smoke')
    def test_bulk_create_delete_network(self):
        # Creates 2 networks in one request
        network_names = [data_utils.rand_name('network-'),
                         data_utils.rand_name('network-')]
        body = self.client.create_bulk_network(network_names)
        created_networks = body['networks']
        self.addCleanup(self._delete_networks, created_networks)
        # Asserting that the networks are found in the list after creation
        body = self.client.list_networks()
        networks_list = [network['id'] for network in body['networks']]
        for n in created_networks:
            self.assertIsNotNone(n['id'])
            self.assertIn(n['id'], networks_list)

    @test.attr(type='smoke')
    def test_bulk_create_delete_subnet(self):
        networks = [self.create_network(), self.create_network()]
        # Creates 2 subnets in one request
        cidr = netaddr.IPNetwork(CONF.network.tenant_network_cidr)
        mask_bits = CONF.network.tenant_network_mask_bits
        cidrs = [subnet_cidr for subnet_cidr in cidr.subnet(mask_bits)]
        names = [data_utils.rand_name('subnet-') for i in range(len(networks))]
        subnets_list = []
        # TODO(raies): "for IPv6, version list [4, 6] will be used.
        # and cidr for IPv6 will be of IPv6"
        ip_version = [4, 4]
        for i in range(len(names)):
            p1 = {
                'network_id': networks[i]['id'],
                'cidr': str(cidrs[(i)]),
                'name': names[i],
                'ip_version': ip_version[i]
            }
            subnets_list.append(p1)
        del subnets_list[1]['name']
        body = self.client.create_bulk_subnet(subnets_list)
        created_subnets = body['subnets']
        self.addCleanup(self._delete_subnets, created_subnets)
        # Asserting that the subnets are found in the list after creation
        body = self.client.list_subnets()
        subnets_list = [subnet['id'] for subnet in body['subnets']]
        for n in created_subnets:
            self.assertIsNotNone(n['id'])
            self.assertIn(n['id'], subnets_list)

    @test.attr(type='smoke')
    def test_bulk_create_delete_port(self):
        networks = [self.create_network(), self.create_network()]
        # Creates 2 ports in one request
        names = [data_utils.rand_name('port-') for i in range(len(networks))]
        port_list = []
        state = [True, False]
        for i in range(len(names)):
            p1 = {
                'network_id': networks[i]['id'],
                'name': names[i],
                'admin_state_up': state[i],
            }
            port_list.append(p1)
        del port_list[1]['name']
        body = self.client.create_bulk_port(port_list)
        created_ports = body['ports']
        self.addCleanup(self._delete_ports, created_ports)
        # Asserting that the ports are found in the list after creation
        body = self.client.list_ports()
        ports_list = [port['id'] for port in body['ports']]
        for n in created_ports:
            self.assertIsNotNone(n['id'])
            self.assertIn(n['id'], ports_list)


class NetworksIpV6TestJSON(NetworksTestJSON):
    _ip_version = 6

    @test.attr(type='smoke')
    def test_create_delete_subnet_with_gw(self):
        net = netaddr.IPNetwork(CONF.network.tenant_network_v6_cidr)
        gateway = str(netaddr.IPAddress(net.first + 2))
        name = data_utils.rand_name('network-')
        network = self.create_network(network_name=name)
        subnet = self.create_subnet(network, gateway)
        # Verifies Subnet GW in IPv6
        self.assertEqual(subnet['gateway_ip'], gateway)

    @test.attr(type='smoke')
    def test_create_delete_subnet_with_default_gw(self):
        net = netaddr.IPNetwork(CONF.network.tenant_network_v6_cidr)
        gateway_ip = str(netaddr.IPAddress(net.first + 1))
        name = data_utils.rand_name('network-')
        network = self.create_network(network_name=name)
        subnet = self.create_subnet(network)
        # Verifies Subnet GW in IPv6
        self.assertEqual(subnet['gateway_ip'], gateway_ip)

    @test.attr(type='smoke')
    def test_create_list_subnet_with_no_gw64_one_network(self):
        name = data_utils.rand_name('network-')
        network = self.create_network(name)
        ipv6_gateway = self.subnet_dict(['gateway'])['gateway']
        subnet1 = self.create_subnet(network,
                                     ip_version=6,
                                     gateway=ipv6_gateway)
        self.assertEqual(netaddr.IPNetwork(subnet1['cidr']).version, 6,
                         'The created subnet is not IPv6')
        subnet2 = self.create_subnet(network,
                                     gateway=None,
                                     ip_version=4)
        self.assertEqual(netaddr.IPNetwork(subnet2['cidr']).version, 4,
                         'The created subnet is not IPv4')
        # Verifies Subnet GW is set in IPv6
        self.assertEqual(subnet1['gateway_ip'], ipv6_gateway)
        # Verifies Subnet GW is None in IPv4
        self.assertEqual(subnet2['gateway_ip'], None)
        # Verifies all 2 subnets in the same network
        body = self.client.list_subnets()
        subnets = [sub['id'] for sub in body['subnets']
                   if sub['network_id'] == network['id']]
        test_subnet_ids = [sub['id'] for sub in (subnet1, subnet2)]
        self.assertItemsEqual(subnets,
                              test_subnet_ids,
                              'Subnet are not in the same network')

    @testtools.skipUnless(CONF.network_feature_enabled.ipv6_subnet_attributes,
                          "IPv6 extended attributes for subnets not "
                          "available")
    @test.attr(type='smoke')
    def test_create_delete_subnet_with_v6_attributes_stateful(self):
        self._create_verify_delete_subnet(
            gateway=self._subnet_data[self._ip_version]['gateway'],
            ipv6_ra_mode='dhcpv6-stateful',
            ipv6_address_mode='dhcpv6-stateful')

    @testtools.skipUnless(CONF.network_feature_enabled.ipv6_subnet_attributes,
                          "IPv6 extended attributes for subnets not "
                          "available")
    @test.attr(type='smoke')
    def test_create_delete_subnet_with_v6_attributes_slaac(self):
        self._create_verify_delete_subnet(
            ipv6_ra_mode='slaac',
            ipv6_address_mode='slaac')

    @testtools.skipUnless(CONF.network_feature_enabled.ipv6_subnet_attributes,
                          "IPv6 extended attributes for subnets not "
                          "available")
    @test.attr(type='smoke')
    def test_create_delete_subnet_with_v6_attributes_stateless(self):
        self._create_verify_delete_subnet(
            ipv6_ra_mode='dhcpv6-stateless',
            ipv6_address_mode='dhcpv6-stateless')
