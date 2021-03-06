
from __future__ import division

from .incremental import IncrementalMoveCache
from .kmc import weighted_choice

# An Event is a (physically meaningful) State transition which occurs
#  through some stochastic process.
# One randomly chosen Event occurs every step of the computation.
# The term is used rather loosely.

# A Move is an event that has a fully determined outcome.
# That is, given an initial State and a Move, the final state is uniquely
#  specified, without randomness.

# Oftentimes, many Moves can be classified under a single umbrella;
# e.g. in the absence of second order effects, the action of creating a
# vacancy will have the same energy barrier regardless of where it is placed.
# In such cases, these similar Moves are said to be of the same Kind.

# A Rule is an object that produces Moves. Each rule has its own set of Kinds.

# A common name used for Rules with a single Kind
DEFAULT_KIND = 'natural'  # (used as config key, and key in MoveCache)

# FIXME move
eV_PER_J = 6.24150913e18
BOLTZMANN__J_PER_K  = 1.38064852e-23
BOLTZMANN__eV_PER_K = BOLTZMANN__J_PER_K * eV_PER_J

class KmcSim:
	'''
	Runs the KMC simulation.

	Is tasked with managing the initialization, reinitialization,
	and the setup of incremental update mechanisms for the various
	components of the computation.
	'''
	def __init__(self, initial_state, rule_specs, temperature=None, incremental=True):
		self.state = None
		self.rule_specs = list(rule_specs)
		self.temperature = temperature
		self.incremental = incremental
		self.initialize(initial_state)

	def initialize(self, state=None):
		'''
		Perform expensive reinitialization.

		If a ``state`` is provided it will replace the current state.
		(the input object will not be modified by the sim)
		'''
		if state is not None:
			self.state = state.clone()
		assert self.state is not None # one was required at construction

		# Regenerate rules
		self.rules_and_rates = {}
		for spec in self.rule_specs:
			# FIXME temperature config
			rule = spec.make_rule(self.state)
			rates = spec.rates(self.temperature)

			# we can finally validate the kinds in the rule_spec now
			#  that we have instantiated the rule...
			self.__validate_kinds(rule, rates)

			self.rules_and_rates[rule] = rates

	@staticmethod
	def __validate_kinds(rule, rates):
		from warnings import warn
		for kind in rule.kinds():
			if kind not in rates:
				raise RuntimeError('config: %s: Missing required rate for kind: %s' % (rule.format(kind)))
		for kind in rates:
			if kind not in rule.kinds():
				warn('config: %s: Unexpected kind: %s' % (rule.format(kind)))

	def rate(self, rule, kind):
		return self.rules_and_rates[rule][kind]

	def rates_info(self):
		d = {}
		for (rule, rates) in self.rules_and_rates.items():
			for (kind,rate) in rates.items():
				d[rule.format(kind)] = rate
		return d

	def __rule_kind_counts(self):
		from collections import Counter
		# Gather info on all kinds across all rules.
		counts = Counter()
		sources = {}
		for rule in self.rules_and_rates:
			# Count how many moves there are of each kind,
			# randomly resolving kinds for ambiguous moves.
			(rule_counts, rule_sources) = rule.move_cache.randomly_decided_counts()

			# Tag kinds with the rules that own them in the output counter.
			counts += { (rule,kind):count for (kind,count) in rule_counts.items() }
			sources[rule] = rule_sources

		return (counts, sources)

	def perform_random_move(self):
		'''
		Select and perform a random change to occur to the state.

		Outputs a dict summary.
		'''
		from math import fsum

		if not self.incremental:
			self.initialize()

		(counts, sources) = self.__rule_kind_counts()

		# Choose which rule and kind of move should occur
		k_w_pairs = [((rule,kind), count * self.rate(rule, kind))
		             for ((rule,kind), count) in counts.items()]
		(rule, kind) = weighted_choice(k_w_pairs)

		# Choose a single move of this kind
		# (moves of the same kind share the same rate, so the choice is uniform)
		move = rule.move_cache.random_by_kind(kind,
			sources[rule], check_total=counts[(rule,kind)])

		# Perform it. (all mutation occurs here!)
		self.perform_given_move(rule, move)

		# Produce a summary of what happened.
		d = {
			'rule': rule.format(),
			'move': rule.info(move),
			'kind': kind,
			'rate': self.rate(rule, kind), # FIXME could be summarized in a table beforehand
			'total_rate': fsum(r for (_,r) in k_w_pairs),
		}
		# FIXME bit of a hack; perhaps this shouldn't be *on* the state?
		if self.state.is_zobrist_enabled():
			d['zobrist'] = self.state.zobrist_key()
		return d

	def perform_given_move(self, rule, move):
		'''
		Perform a selected move, modifying the state and all objects that depend on it.
		'''
		affected_nodes = tuple(rule.nodes_affected_by(move))

		for r in self.rules_and_rates:
			r.pre_status_change(self.state, affected_nodes)

		rule.perform(move, self.state)

		for r in self.rules_and_rates:
			r.post_status_change(self.state, affected_nodes)

	def validate(self):
		'''
		Perform an expensive self-integrity check.

		Raises an exception or returns True (for use in assert).
		'''
		self.state.validate()
		for rule in self.rules_and_rates:
			rule.validate(self.state)
		return True

class RuleSpec:
	''' Generates a Rule and describes its rates. '''
	def __init__(self, rule_class, rates, rate_is_barrier, init_kw):
		self.__klass = rule_class
		self.__rates = rates
		self.__rate_is_barrier = rate_is_barrier
		self.__init_kw = init_kw

	# FIXME behavior when barrier is specified is unusual...
	def __rate_from_energy(self, barrier_ev, temperature_k):
		from math import exp
		return exp(-barrier_ev / (temperature_k * BOLTZMANN__eV_PER_K))
	def __energy_from_rate(self, rate, temperature_k):
		from math import log
		return -temperature_k * BOLTZMANN__eV_PER_K * log(rate)

	def rates(self, temperature=None):
		if self.__rate_is_barrier:
			if temperature is None:
				raise ValueError('must specify temperature to compute rates from barrier')
			return {
				k:self.__rate_from_energy(v, temperature)
				for (k,v) in self.__rates.items()
			}
		else:
			return dict(self.__rates)

	def make_rule(self, state):
		return self.__klass(state, self.__init_kw)

# NOTE: The role of a Rule is a bit uncertain;
# The original intent was for them to be stateless bundles of
# callbacks, but they now have a stateful aspect (the move_cache).
class Rule:
	def __init__(self, initial_state, init_kw):
		self.move_cache = IncrementalMoveCache()
		self.initialize_moves(initial_state)

		# Give additional keywords to subinit.
		# These may come from config, so validate them.
		from inspect import getargspec
		(args,_,_,_) = getargspec(self.subinit)
		bad_kw_args = set(init_kw) - (set(args) - set(['self']))
		if bad_kw_args:
			raise RuntimeError('unknown property of %s: %r' %
				(self.format(), bad_kw_args.pop()))
		self.subinit(**init_kw)

	def __compute_move_cache(self, state):
		# FIXME monkey patching an initialization function, really?
		#       especially one that is an abstract member!?
		tmp = self.move_cache
		self.move_cache = IncrementalMoveCache()

		self.initialize_moves(state)

		out = self.move_cache
		self.move_cache = tmp
		return out

	def __validate_move_cache(self, state):
		expected = self.__compute_move_cache(state)
		self.move_cache.validate_against(expected)

	def format(self, kind=None):
		''' Stringify name of rule, or the qualified name of a kind. '''
		if kind is None: return type(self).__name__[len('Rule'):]
		else: return '%s:%s' % (self.format(), kind)

	def validate(self, state):
		'''
		Perform an expensive self-integrity check, given the state.

		Throws an exception or returns True (for use in assert).
		'''
		self.__validate_move_cache(state)
		return True

	# API for the KMC engine

	def subinit(self):
		''' Init for rule-specific properties. (i.e. store config flags) '''
		pass

	def perform(self, move, state):
		''' Perform the given move on the state, mutating it. '''
		raise NotImplementedError

	def info(self, move):
		''' Return a dict of serializable data describing the move, for output. '''
		raise NotImplementedError

	def kinds(self):
		''' Return an iterable of the Kinds that the Rule may produce,
		for checking against the list provided in the config. '''
		return [DEFAULT_KIND]

	def initialize_moves(self, initial_state):
		''' Callback to set up the list of moves in move_cache from scratch.
		(assuming it is initially empty). '''
		raise NotImplementedError

	def nodes_affected_by(self, move):
		''' Get an iterable of nodes whose status may change as a result of a move.
		(these will be the nodes that show in the status_change event)'''
		raise NotImplementedError

	# make debug output more readible
	def __repr__(self): return type(self).__name__

	# convenience methods intended to be used by the Rule subclasses
	# (move_cache mixin)

	def add_move(self, move, kind=DEFAULT_KIND):
		self.move_cache.add(move, kind)

	def clear_move(self, move):
		assert self.move_cache.has_move(move)
		self.move_cache.clear_all(move)

