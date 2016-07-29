
from . import rules
from .sim import RuleSpec
from .sim import DEFAULT_KIND

__all__ = ['parse']

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
		try: rules_map = config.pop('rules')
		except KeyError: raise RuntimeError('config missing required section: rules')

		for name in list(rules_map):
			try: klass = getattr(rules, name)
			except KeyError: raise RuntimeError('unknown rule: %s' % name)

			yield build_rule_spec(name, klass, rules_map.pop(name))
	return list(inner())

def build_rule_spec(name, klass, rule_map):
	def err(msg, *args):
		raise RuntimeError('config: %s: %s' % (name, msg % args))

	# did user provide an energy barrier or a rate?
	barrier_map = rule_map.pop('barrier', None)
	rate_map = rule_map.pop('rate', None)
	if (not barrier_map) and (not rate_map):
		err('neither barrier nor rate specified')
	if barrier_map and rate_map:
		err('barrier and rate both specified')
	the_map = barrier_map or rate_map
	map_key = 'barrier' if barrier_map else 'rate'

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
