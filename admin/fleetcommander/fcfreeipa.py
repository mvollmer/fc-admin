# -*- coding: utf-8 -*-
# vi:ts=2 sw=2 sts=2

# Copyright (C) 2015 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the licence, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, see <http://www.gnu.org/licenses/>.
#
# Authors: Alberto Ruiz <aruiz@redhat.com>
#          Oliver Gutiérrez <ogutierrez@redhat.com>

import json
import logging
from functools import wraps

from ipalib import api
from ipalib import errors


FC_WILDCARD_HOSTGROUP = u'fc_all_hosts'


logging.getLogger().setLevel(logging.DEBUG)


def connection_required(f):
    @wraps(f)
    def wrapped(obj, *args, **kwargs):
        if not api.isdone('bootstrap'):
            obj.connect()
        return f(obj, *args, **kwargs)
    return wrapped


class IPAConnectionError(Exception):
    pass


class RenameToExistingException(Exception):
    pass


class FreeIPAConnector(object):

    def connect(self, sanity_check=True):
        """
        Connect to FreeIPA server
        """
        try:
            if not api.isdone('bootstrap'):
                api.bootstrap(context='cli', log=None)
                api.finalize()
            if not api.Backend.rpcclient.isconnected():
                api.Backend.rpcclient.connect()
            api.Command.ping()
            # Sanity check
            if sanity_check:
                self._do_sanity_check()
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error connecting to FreeIPA: %s' % e)
            raise

    def _create_profile(self, profile):
        name = unicode(profile['name'])
        logging.debug(
            'FreeIPAConnector: Creating profile %s' % name)
        try:
            api.Command.deskprofile_add(
                name,
                description=unicode(profile['description']),
                ipadeskdata=json.dumps(profile['settings'])
            )
            self._create_profile_rules(profile)
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error creating profile: %s' % e)
            self.del_profile(name)
            raise e

    def _create_profile_rules(self, profile):
        name = unicode(profile['name'])
        # Save rule for profile
        logging.debug(
            'FreeIPAConnector: Creating profile rule for %s' % name)
        api.Command.deskprofilerule_add(
            name,
            ipadeskprofiletarget=name,
            ipadeskprofilepriority=profile['priority'])
        # Save rules for users
        users = map(unicode, profile['users'])
        groups = map(unicode, profile['groups'])
        logging.debug(
            'FreeIPAConnector: Creating users rules for profile %s: %s, %s' % (
                name, users, groups))
        api.Command.deskprofilerule_add_user(name, user=users, group=groups)
        # Save rules for hosts
        hosts = map(unicode, profile['hosts'])
        hostgroups = map(unicode, profile['hostgroups'])
        logging.debug(
            'FreeIPAConnector: Creating hosts rules for profile %s: %s, %s' % (
                name, hosts, hostgroups))
        api.Command.deskprofilerule_add_host(
            name, host=hosts, hostgroup=hostgroups)

    def _update_profile(self, profile, oldname=None):
        name = unicode(profile['name'])

        parms = {
            'cn': name,
            'description': unicode(profile['description']),
            'ipadeskdata': json.dumps(profile['settings'])
        }

        if oldname is not None:
            parms['cn'] = oldname
            parms['rename'] = name
            # Update profile renaming it
            logging.debug(
                'FreeIPAConnector: Updating profile %s and renaming to %s' % (
                    oldname, name))
        else:
            logging.debug(
                'FreeIPAConnector: Updating profile %s' % name)
        try:
            api.Command.deskprofile_mod(**parms)
        except errors.EmptyModlist:
            pass
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error updating profile %s: %s' % (name, e))
            raise e
        # Update rules for profile
        self._update_profile_rules(profile, oldname=oldname)

    def _update_profile_rules(self, profile, oldname=None):
        name = unicode(profile['name'])

        parms = {
            'cn': name,
            'ipadeskprofiletarget': name,
            'ipadeskprofilepriority': profile['priority']
        }

        if oldname is not None:
            # Update profile renaming it
            logging.debug(
                'FreeIPAConnector: Updating profile rule %s and renaming to %s' % (
                    oldname, name))
            parms['cn'] = oldname
            parms['rename'] = name
        else:
            logging.debug(
                'FreeIPAConnector: Updating profile rules for %s' % name)

        try:
            api.Command.deskprofilerule_mod(**parms)
        except errors.EmptyModlist:
            pass
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error updating rule for profile %s: %s - %s' % (
                    name, e, e.__class__))
            raise e

        # Get current users, groups, hosts and hostgroups for this rule
        rule = self.get_profile_rule(name)
        applies = self._get_profile_applies_from_rule(rule)
        # Get users and groups to add
        udif = set(profile['users']) - set(applies['users'])
        gdif = set(profile['groups']) - set(applies['groups'])
        # Add the users and groups to rule
        api.Command.deskprofilerule_add_user(
            name,
            user=map(unicode, udif),
            group=map(unicode, gdif)
        )
        # Get users and groups to remove
        udif = set(applies['users']) - set(profile['users'])
        gdif = set(applies['groups']) - set(profile['groups'])
        # Remove users and groups from rule
        api.Command.deskprofilerule_remove_user(
            name,
            user=map(unicode, udif),
            group=map(unicode, gdif)
        )

        # Get hosts and hostgroups to add
        hdif = set(profile['hosts']) - set(applies['hosts'])
        hgdif = set(profile['hostgroups']) - set(applies['hostgroups'])
        # Add the hosts and hostgroups to rule
        api.Command.deskprofilerule_add_host(
            name,
            host=map(unicode, hdif),
            hostgroup=map(unicode, hgdif)
        )
        # Get hosts and hostgroups to remove
        hdif = set(applies['hosts']) - set(profile['hosts'])
        hgdif = set(applies['hostgroups']) - set(profile['hostgroups'])
        # Remove hosts and hostgroups from rule
        api.Command.deskprofilerule_remove_host(
            name,
            host=map(unicode, hdif),
            hostgroup=map(unicode, hgdif)
        )

    def _get_all_hosts(self):
        try:
            hosts = []
            for host in api.Command.host_find(sizelimit=0)['result']:
                hosts.append(host['fqdn'][0])
            return hosts
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error getting hosts list')
            raise

    def _create_automember_wildcard_hostgroup(self):
        """
        Initialize an automember hostgroup for Fleet Commander and
        add all current machines into it
        """

        # Create hostgroup
        logging.debug(
            'FreeIPAConnector: Creating fleet commander wildcard hostgroup "%s"' % FC_WILDCARD_HOSTGROUP)
        try:
            logging.debug(
                'FreeIPAConnector: Creating wildcard hostgroup "%s"' % FC_WILDCARD_HOSTGROUP)
            api.Command.hostgroup_add(FC_WILDCARD_HOSTGROUP)
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error creating fleet commander wildcard hostgroup "%s": %s' % (
                    FC_WILDCARD_HOSTGROUP, e))
            _rollback()
            raise e
        # Create automember rule
        try:
            logging.debug(
                'FreeIPAConnector: Creating automember rule')
            api.Command.automember_add(FC_WILDCARD_HOSTGROUP, type=u'hostgroup')
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error creating automember rule for wildcard hostgroup: %s' % e)
            _rollback()
            raise e
        # Create automember rule condition
        try:
            logging.debug(
                'FreeIPAConnector: Creating automember condition')
            api.Command.automember_add_condition(FC_WILDCARD_HOSTGROUP, type=u'hostgroup', key=u'fqdn', automemberinclusiveregex=u'.*')
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error creating automember rule for wildcard hostgroup: %s' % e)
            _rollback()
            raise e
        # Add all hosts to hostgroup
        try:
            logging.debug(
                'FreeIPAConnector: Adding all existent hosts to wildcard group')
            hosts = self._get_all_hosts()
            api.Command.hostgroup_add_member(FC_WILDCARD_HOSTGROUP, host=hosts)
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error adding hosts to wildcard hostgroup: %s' % e)
            raise e

    def _remove_automember_wildcard_hostgroup(self):
        logging.debug(
            'FreeIPAConnector: Cleaning fleet commander wildcard hostgroup creation')
        try:
            logging.debug(
                'FreeIPAConnector: Cleaning automember condition')
            api.Command.automember_remove_condition(
                FC_WILDCARD_HOSTGROUP, key=u'fqdn', type=u'hostgroup')
        except Exception, e:
            pass
        try:
            logging.debug(
                'FreeIPAConnector: Cleaning automember rule')
            api.Command.automember_del(
                FC_WILDCARD_HOSTGROUP, type=u'hostgroup')
        except Exception, e:
            pass
        try:
            logging.debug(
                'FreeIPAConnector: Cleaning wildcard host group')
            api.Command.hostgroup_del(FC_WILDCARD_HOSTGROUP)
        except Exception, e:
            pass

    def _do_sanity_check(self):
        """
        Checks IPA server environment and sanity
        """
        logging.debug(
            'FreeIPAConnector: Starting sanity check')
        # Check freeipa-desktop-profile plugin installation
        if not hasattr(api.Command, 'deskprofileconfig_show'):
            raise IPAConnectionError(
                'freeipa-desktop-profile is not installed in FreeIPA server')
        # Check if wildcard group is present
        try:
            result = api.Command.hostgroup_show(FC_WILDCARD_HOSTGROUP)
            hostgroup_exists = True
        except errors.NotFound:
            hostgroup_exists = False
        if not hostgroup_exists:
            # Try to create it
            try:
                self._create_automember_wildcard_hostgroup()
            except Exception, e:
                # Rollback changes
                self._remove_automember_wildcard_hostgroup()
                raise IPAConnectionError(
                    'Could not initialize Fleet Commander wildcard hostgroup')
        return None

    def _get_profile_applies_from_rule(self, rule):
        applies = {
            'users': [],
            'groups': [],
            'hosts': [],
            'hostgroups': [],
        }
        if 'memberuser_user' in rule:
            applies['users'] = rule['memberuser_user']
        if 'memberuser_group' in rule:
            applies['groups'] = rule['memberuser_group']
        if 'memberhost_host' in rule:
            # Remove domain part from hostnames
            applies['hosts'] = [
                x.split('.')[0] for x in rule['memberhost_host']]
        if 'memberhost_hostgroup' in rule:
            # Load hostgroups only if they are not the wildcard group
            if rule['memberhost_hostgroup'] != (FC_WILDCARD_HOSTGROUP,):
                applies['hostgroups'] = rule['memberhost_hostgroup']
            else:
                logging.debug(
                    'FreeIPAConnector: Removed wildcard group from profile applies')

        return applies

    @connection_required
    def check_user_exists(self, username):
        try:
            result = api.Command.user_show(unicode(username))
            return True
        except errors.NotFound:
            return False

    @connection_required
    def check_group_exists(self, groupname):
        try:
            result = api.Command.group_show(unicode(groupname))
            return True
        except errors.NotFound:
            return False

    @connection_required
    def check_host_exists(self, hostname):
        try:
            result = api.Command.host_show(unicode(hostname))
            return True
        except errors.NotFound:
            return False

    @connection_required
    def check_hostgroup_exists(self, groupname):
        try:
            result = api.Command.hostgroup_show(unicode(groupname))
            return True
        except errors.NotFound:
            return False

    @connection_required
    def check_profile_exists(self, name):
        try:
            result = api.Command.deskprofile_show(unicode(name), all=False)
            return True
        except errors.NotFound:
            return False

    @connection_required
    def get_global_policy(self):
        policydata = api.Command.deskprofileconfig_show()
        return int(policydata['result']['ipadeskprofilepriority'][0])

    @connection_required
    def set_global_policy(self, policy):
        try:
            api.Command.deskprofileconfig_mod(
                ipadeskprofilepriority=policy)
        except errors.EmptyModlist:
            pass
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error setting global policy to %s: %s' % (
                    policy, e))
            raise e

    @connection_required
    def save_profile(self, profile):
        # Check if we need to add the wildcard hostgroup
        if not profile['hosts'] and not profile['hostgroups']:
            profile['hostgroups'].append(FC_WILDCARD_HOSTGROUP)
            logging.debug(
                'FreeIPAConnector: Added wildcard hostgroup to profile applies')

        name = profile['name']
        # Check if profile has an "oldname" field so we need to rename it
        if 'oldname' in profile and name != profile['oldname']:
            oldname = profile['oldname']
            # Modify it
            logging.debug(
                'FreeIPAConnector: Profile needs renaming from %s to %s' % (
                    profile['oldname'], name))
            # Check new name exists
            if self.check_profile_exists(name):
                # Profile can not be renamed to an existing name
                logging.error(
                    'FreeIPAConnector: Profile %s can not be renamed to existing name %s' % (
                        oldname, name))
                raise RenameToExistingException(
                    'Profile %s can not be renamed to existing name %s' % (
                        oldname, name))
            else:
                # Rename profile
                return self._update_profile(profile, oldname=oldname)
        else:
            # Check if profile already exists
            if self.check_profile_exists(name):
                # Modify it
                logging.debug(
                    'FreeIPAConnector: Profile %s already exists. Updating' % name)
                return self._update_profile(profile)
            else:
                # Save new
                logging.debug(
                    'FreeIPAConnector: Profile %s does not exist. Creating' % name)
                return self._create_profile(profile)

    @connection_required
    def del_profile(self, name):
        name = unicode(name)
        logging.debug(
            'FreeIPAConnector: Deleting profile %s' % name)
        try:
            api.Command.deskprofile_del(name)
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error removing profile %s. %s - %s' % (
                    name, e, e.__class__))

        logging.debug(
            'FreeIPAConnector: Deleting profile rule for %s' % name)
        try:
            api.Command.deskprofilerule_del(name)
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error removing rule for profile %s. %s - %s' % (
                    name, e, e.__class__))

    @connection_required
    def get_profiles(self):
        try:
            results = api.Command.deskprofile_find('', sizelimit=0, all=True)
        except Exception, e:
            logging.error(
                'FreeIPAConnector: Error getting profiles: %s - %s' % (
                    e, e.__class__))
        else:
            resultlist = []
            for res in results['result']:
                desc = ''
                if 'description' in res:
                    desc = res['description'][0]
                resultlist.append(
                    (res['cn'][0], desc)
                )
            return resultlist

    @connection_required
    def get_profile(self, name):
        name = unicode(name)
        try:
            result = api.Command.deskprofile_show(name, all=True)
        except Exception, e:
            logging.error(
                'Error getting profile %s: %s. %s' % (name, e, e.__class__))
            raise e
        rule = self.get_profile_rule(name)
        data = result['result']
        profile = {
            'name': data['cn'][0],
            'description': data.get('description', ('',))[0],
            'priority': int(rule['ipadeskprofilepriority'][0]),
            'settings': json.loads(data['ipadeskdata'][0]),
        }
        applies = self._get_profile_applies_from_rule(rule)
        profile.update(applies)
        return profile

    @connection_required
    def get_profile_rule(self, name):
        logging.debug(
            'FreeIPAConnector: Getting profile rule for ""%s"' % name)
        name = unicode(name)
        try:
            result = api.Command.deskprofilerule_show(name, all=True)
        except Exception, e:
            logging.error(
                'Error getting rule for profile %s: %s. %s' % (
                    name, e, e.__class__))
            raise e
        rule = result['result']
        logging.debug('FreeIPAConnector: Obtained rule data: %s' % rule)
        return rule
