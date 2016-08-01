
from . import rules
from .sim import RuleSpec
from .sim import DEFAULT_KIND

import logging
import yaml

def from_dict(d):
	if not isinstance(d, dict):
		raise RuntimeError('config: document is not a YAML mapping')

	out = {
		'rule_specs': consume__rule_specs(d),
		# consume__other_stuff...
	}
	if d:
		raise RuntimeError('config: unrecognized item: %r' % d.popitem()[0])
	return out

def consume__rule_specs(config):
	def inner():
		rules_map = pop_required(config, 'rules')

		for name in list(rules_map):
			try: klass = getattr(rules, name)
			except KeyError: raise RuntimeError('unknown rule: %s' % name)

			yield build_rule_spec(name, klass, rules_map.pop(name))
	return list(inner())

def build_rule_spec(name, klass, rule_map):
	def err(msg, *args):
		error(msg % args, where=name)

	# did user provide an energy barrier or a rate?
	(map_key, the_map) = pop_mutually_exclusive(rule_map, ['barrier', 'rate'], where=name)

	# normalize shorthand for single-kind rule
	if isinstance(the_map, (int,float)):
		the_map = {DEFAULT_KIND: the_map}

	# misc validation
	if not isinstance(the_map, dict):
		err('barrier/rate must be a real number or a mapping')
	if not all(isinstance(x,(int,float)) for x in the_map.values()):
		err('non-numeric energy barrier or rate')
	if any(x < 0 for x in the_map.values()):
		err('negative energy barrier or rate')

	# float conversion
	the_map = {k:float(v) for (k,v) in the_map.items()}

	return RuleSpec(
		rule_class=klass,
		rates=the_map,
		rate_is_barrier=(map_key == 'barrier'),
		init_kw=rule_map, # other fields regarded as kw args to subinit
	)

#----------------------------------------------------------
# helpers

def error(msg='', where=''):
	s = 'config: ' + where + (': ' if where else '') + msg
	raise RuntimeError(s)

def pop_required(d, key, where=''):
	try: return d.pop(key)
	except KeyError:
		error('missing required key: ' + repr(key), where)

def pop_mutually_exclusive(d, keys, default=None, where=''):
	def err():
		s = 'need ' + ('at most ' if default else 'exactly ')
		s += 'one of: ' + ', '.join(map(repr,keys))
		error(s, where)

	found = [x for x in keys if x in d]
	if len(found) > 1: err()
	elif len(found) == 0:
		if default is None: err()
		else: return default
	key, = found
	return (key, d.pop(key))

def merge(left, right, path=()):
	# recursively merge dictionaries
	if dict == type(left) == type(right):
		out = {}
		for key in set(left) | set(right):
			if key in left and key in right:
				out[key] = merge(left[key], right[key], path + (key,))
			elif key in left:  out[key] = left[key]
			elif key in right: out[key] = right[key]
			else: assert False, 'huh?'
		return out
	# prefer the newer value, but be vocal.
	else:
		if left != right:
			pathstr = ':'.join(map(repr,path)) or 'root'
			logging.info('config key overriden at %s\n  old: %r\n  new: %r', pathstr, left, right)
		return right

def load_all(files):
	from functools import reduce

	dicts = list(map(yaml.load, files))

	# empty file in yaml is None
	if any(d is None for d in dicts):
		logging.debug('empty config file')
	dicts = [x for x in dicts if x is not None]

	if not all(isinstance(d, dict) for d in dicts):
		error('config must be a YAML mapping')

	return reduce(merge, dicts, {})
