
from __future__ import division

from collections import defaultdict
import itertools
import logging
from termcolor import colored

from .incremental import IncrementalMoveCache
from . import kmc
import hexagonal as hex

try: import cPickle as pickle
except ImportError: import pickle

# FIXME these shouldn't be constant.  They are right now simply so
#  the script can run
RATE_CREATE_VACANCY = 1.
RATE_MIGRATE_VACANCY = 1.
RATE_CREATE_TREFOIL = 50.
RATE_DESTROY_TREFOIL = 25.

# Node occupation flags used in the node status cache
STATUS_NO_VACANCY = 0
STATUS_DIVACANCY = 1
STATUS_TREFOIL_PARTICIPANT = 2

# Names identifying the layer to which a point vacancy belongs.
# This is just kind of a "general idea".
LAYER_DIVACANCY = 'both'
LAYER_MONOVACANCY_1 = 'top'
LAYER_MONOVACANCY_2 = 'bottom'

class State:

	def __init__(self, dim, emit):
		self.grid = Grid(dim)
		# FIXME so this was a bad idea; surprisingly, it looks like bound member
		#  functions can be pickled; unsurprisingly, it needs to create new copies
		#  of the bound class objects when unpickling.
		# As a result, the presence of the emit member indirectly causes clone()
		#  to create a brand new IncrementalNodeCache.
		self.emit = emit
		self.__vacancies = {}
		self.__trefoils = {}
		self.__nodes = self.__compute_nodes_lookup()
		self.__next_id = 0

	def dim(self):
		return self.grid.dim

	def clone(self):
		return pickle.loads(pickle.dumps(self))

	#------------------------------------------
	# FIXME: I think I may want to switch these dicts out for named tuples,
	#  to help dodge bugs caused by mispelling keys in __setitem__

	def __compute_nodes_lookup(self):
		''' generates __nodes from __vacancies and __trefoils '''
		cache = {
			x: {'status': STATUS_NO_VACANCY, 'owner': None }
			for x in self.grid.nodes()
		}

		for id, v in self.__vacancies.items():
			assert v['layer'] == LAYER_DIVACANCY, ('looks like this function'
				' (and all users of status functions) needs updating')
			node = v['where']
			cache[node]['status'] = STATUS_DIVACANCY
			cache[node]['owner'] = id

		for id, v in self.__trefoils.items():
			for node in v['where']:
				cache[node]['status'] = STATUS_TREFOIL_PARTICIPANT
				cache[node]['owner'] = id

		return cache

	def __debug_validate_nodes_lookup(self):
		def run_in_debug_only():
			expected = self.__compute_nodes_lookup()
			actual   = self.__nodes

			missing_nodes = set(expected) - set(actual)
			if missing_nodes:
				raise AssertionError("node not in lookup: {!r}".format(missing_nodes.pop()))

			unexpected_nodes = set(actual) - set(expected)
			if unexpected_nodes:
				raise AssertionError("unexpected node in lookup: {!r}".format(unexpected_nodes.pop()))

			for n in expected:
				if expected[n] != actual[n]:
					raise AssertionError("bad data for node {!r}\n"
						"  In Table: {!r}\n"
						"  Expected: {!r}".format(n, actual[n], expected[n]))

			return True

		assert run_in_debug_only()

	#------------------------------------------
	# Accessors/iterators

	def vacancies(self): return self.__vacancies.__iter__()
	def vacancy_node(self, id): return self.__vacancies[id]['where']
	def vacancy_layer(self, id): return self.__vacancies[id]['layer']
	def vacancies_with_id(self): return self.__vacancies.items()

	def nodes(self): return self.grid.nodes()
	def node_status(self, node): return self.__nodes[node]['status']
	def node_vacancy_id(self, node): return self.__nodes[node]['owner']
	def nodes_with_status(self): return [(n, self.node_status(n)) for n in self.nodes()]

	def trefoils(self): return self.__trefoils.__iter__()
	def trefoil_nodes(self, id): return self.__trefoils[id]['where']
	def trefoils_with_id(self): return self.__trefoils.items()

	#------------------------------------------
	# Public mutators
	# These are discrete actions which modify the State and perform
	# incrementalized updates to all caches, so that all objects
	# are left in a consistent state.

	# General flow is:
	# * Emit a message to objects dependent on the State.  This is done
	#   first so they can see how the state looks before the change.
	# * Update the primary storage (__vacancies, __trefoils)
	# * Update the __nodes cache (this is not done via `emit` because other
	#   objects depend on the node cache).

	# NOTES on implementation constraints:
	# * These methods should be regarded as the primitive operations for
	#   modifying the State.  Any other operations are composed of these.
	# * They must be members of State so that they can modify private members.
	# * They contain 'emit' calls to ensure that all composite operations
	#   send the necessary messages.
	# * In theory, the emit member could be removed, and another object with a
	#   parallel set of methods could first call emit and then call these methods.
	#   But then composite operations would have to be implemented on that object
	#   as well; not this class.

	def new_vacancy(self, node):
		self.emit('pre_new_vacancy', self, node)
		self.emit('pre_status_change', self, [node])

		id = self.__consume_id()
		self.__vacancies[id] = {'where': tuple(node)}
		self.__nodes[node]['status'] = STATUS_DIVACANCY
		self.__nodes[node]['owner'] = id

		self.emit('post_new_vacancy', self, node)
		self.emit('post_status_change', self, [node])

	def new_trefoil(self, nodes):
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3

		self.emit('pre_new_trefoil', self, nodes)
		self.emit('pre_status_change', self, nodes)

		id = self.__consume_id()
		self.__trefoils[id] = {'where': nodes}
		for n in nodes:
			self.__nodes[n]['status'] = STATUS_TREFOIL_PARTICIPANT
			self.__nodes[n]['owner'] = id

		self.emit('post_new_trefoil', self, nodes)
		self.emit('post_status_change', self, nodes)

	def pop_vacancy(self, node):
		self.emit('pre_del_vacancy', self, node)
		self.emit('pre_status_change', self, [node])

		id = self.__find_vacancy(node)
		vacancy = self.__vacancies.pop(id)
		self.__nodes[node]['status'] = STATUS_NO_VACANCY
		self.__nodes[node]['owner'] = None

		self.emit('post_del_vacancy', self, node)
		self.emit('post_status_change', self, [node])
		return vacancy

	def pop_trefoil(self, nodes):
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3

		self.emit('pre_del_trefoil', self, nodes)
		self.emit('pre_status_change', self, nodes)

		id = self.__find_trefoil(nodes)
		trefoil = self.__trefoils.pop(id)
		for node in nodes:
			self.__nodes[node]['status'] = STATUS_NO_VACANCY
			self.__nodes[node]['owner'] = None

		self.emit('post_del_trefoil', self, nodes)
		self.emit('post_status_change', self, nodes)
		return trefoil

	def __find_vacancy(self, node):
		id = self.__nodes[node]['owner']
		assert self.__vacancies[id]['where'] == node
		return id

	def __find_trefoil(self, nodes):
		nodes = frozenset(nodes)
		id = self.__nodes[nodes[0]]['owner']
		assert self.__trefoils[id]['where'] == nodes
		return id

	#------------------------------------------
	# Low-level mutators
	# These do not necessarily leave the object in a consistent state.

	def __consume_id(self):
		id = self.__next_id
		self.__next_id = self.__next_id + 1
		assert id not in self.__vacancies
		assert id not in self.__trefoils
		return id


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


# FIXME Name is dumb
class RuleSet:
	def __init__(self, initial_state, event_manager):
		# FIXME these should be specified via config
		self.rules = [
			RuleCreateVacancy(initial_state, event_manager),
			RuleFillVacancy(initial_state, event_manager),
			RuleMoveVacancy(initial_state, event_manager),
		]
		# FIXME should clone() to avoid mutating input,
		#  but State.clone is currently b0rked.
		self.state = initial_state#.clone()

	def rate(self, rule, kind):
		# FIXME should be based on energy barrier and boltzmann
		return rule.kinds()[kind]

	def __rule_kind_counts(self):
		from collections import Counter
		# Gather info on all kinds across all rules.
		counts = Counter()
		sources = {}
		for rule in self.rules:
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

		(counts, sources) = self.__rule_kind_counts()

		# Choose which rule and kind of move should occur
		k_w_pairs = [((rule,kind), count * self.rate(rule, kind))
		             for ((rule,kind), count) in counts.items()]
		(rule, kind) = kmc.weighted_choice(k_w_pairs)

		# Choose a single move of this kind
		# (moves of the same kind share the same rate, so the choice is uniform)
		move = rule.move_cache.random_by_kind(kind,
			sources[rule], check_total=counts[(rule,kind)])

		# Perform it.
		rule.perform(move, self.state) # CAUTION: Mutates the State and MoveCache

		# Produce a summary of what happened.
		return {
			'move': dict(rule=type(rule).__name__, **rule.info(move)),
			'rate': self.rate(rule, kind),
			'total_rate': fsum(r for (_,r) in k_w_pairs),
		}


class GoldStandardRuleSet(RuleSet):
	''' extremely temperamental debugging object that provides non-incremental ruleset updates '''
	def __init__(self, initial_state, *args, **kw):
		# We're just going to... hang on to these.
		# Certainly nothing suspicious going on around here, nope!
		self.init_args = args
		self.init_kw   = kw
		super().__init__(initial_state, *args, **kw)

	def __reinitialize_move_cache(self):
		# ... <_< ...
		# ... >_> ...
		super().__init__(self.state, *self.init_args, **self.init_kw)

	def perform_random_move(self):
		self.__reinitialize_move_cache()
		return super().perform_random_move()

# NOTE: The role of a Rule is a bit uncertain;
# The original intent was for them to be stateless bundles of
# callbacks, but they now have a stateful aspect (the move_cache).
class Rule:
	def __init__(self, initial_state, event_man):
		self.move_cache = IncrementalMoveCache()
		self.initialize_moves(initial_state)

		# implementations of these required on each subclass
		event_man.add_listeners_from(self)

	# API for the KMC engine

	def perform(self, move, state):
		''' Perform the given move on the state, mutating it. '''
		raise NotImplementedError

	def info(self, move):
		''' Return a dict of serializable data describing the move, for output. '''
		raise NotImplementedError

	def kinds(self):
		''' Return a list of [(kind, individual_weight)] '''
		raise NotImplementedError

	# Callbacks to modify move_cache

	# callback to set up the list of moves in move_cache from scratch
	# (assuming there is initially nothing belonging to this rule in there)
	def initialize_moves(self, initial_state): raise NotImplementedError

	# callbacks to incrementally update the list of moves in move_cache
	def on_new_vacancy(self, initial_state): raise NotImplementedError
	def on_del_vacancy(self, initial_state): raise NotImplementedError
	def on_new_trefoil(self, initial_state): raise NotImplementedError
	def on_del_trefoil(self, initial_state): raise NotImplementedError

	# make debug output more readible
	def __repr__(self): return type(self).__name__

	# convenience methods intended to be used by the Rule subclasses
	# (move_cache mixin)

	def add_move(self, move, kind=None):
		self.move_cache.add(move, kind)

	def clear_move(self, move):
		assert self.move_cache.has_move(move)
		self.move_cache.clear_all(move)

class RuleCreateVacancy(Rule):
	def perform(self, node, state):
		state.new_vacancy(node)

	def info(self, node): return { 'node': node }
	def kinds(self): return { None: 2.0 }

	def initialize_moves(self, state):
		for (node,status) in state.nodes_with_status():
			if status is STATUS_NO_VACANCY:
				self.add_move(node)

	# Invalidate nodes that change.
	def pre_status_change(self, state, nodes):
		for node in nodes:
			if state.node_status(node) is STATUS_NO_VACANCY:
				self.clear_move(node)
	def post_status_change(self, state, nodes):
		for node in nodes:
			if state.node_status(node) is STATUS_NO_VACANCY:
				self.add_move(node)

class RuleFillVacancy(Rule):
	def perform(self, node, state):
		state.pop_vacancy(node)

	def info(self, node): return { 'node': node }
	def kinds(self): return { None: 1.0 }

	def initialize_moves(self, state):
		for (node,status) in state.nodes_with_status():
			if status is STATUS_DIVACANCY:
				self.add_move(node)

	# Invalidate nodes that change.
	def pre_status_change(self, state, nodes):
		for node in nodes:
			if state.node_status(node) is STATUS_DIVACANCY:
				self.clear_move(node)
	def post_status_change(self, state, nodes):
		for node in nodes:
			if state.node_status(node) is STATUS_DIVACANCY:
				self.add_move(node)

class RuleMoveVacancy(Rule):
	def perform(self, move, state):
		(old,new) = move
		state.pop_vacancy(old)
		state.new_vacancy(new)

	def info(self, move):
		(old,new) = move
		return { 'was': old, 'now': new }
	def kinds(self): return { None: 1.0 }

	def initialize_moves(self, state):
		for n in state.grid.nodes():
			[self.add_move((n,nbr)) for nbr in self.eligible_moves(state, n)]

	# Invalidate moves originating at a max distance of 1 from nodes that change.
	def pre_status_change(self, state, nodes):
		for n in state.grid.nodes_in_distance_range(nodes, 0, 1):
			[self.clear_move((n,nbr)) for nbr in self.eligible_moves(state, n)]
	def post_status_change(self, state, nodes):
		for n in state.grid.nodes_in_distance_range(nodes, 0, 1):
			[self.add_move((n,nbr)) for nbr in self.eligible_moves(state, n)]

	# --- helpers ---
	def eligible_moves(self, state, node):
		if state.node_status(node) is STATUS_DIVACANCY:
			for nbr in state.grid.neighbors(node):
				if state.node_status(nbr) is STATUS_NO_VACANCY:
					yield nbr

VALID_EVENTS = set([
	'pre_new_vacancy', 'post_new_vacancy',
	'pre_del_vacancy', 'post_del_vacancy',
	'pre_new_trefoil', 'post_new_trefoil',
	'pre_del_trefoil', 'post_del_trefoil',
	'pre_status_change', 'post_status_change',
])
# alternatively we could use decorators to tag methods that are handlers
# but then I would worry about bugs due to forgetting to tag one
def looks_like_handler(attrname):
	return attrname.startswith('pre_') or attrname.startswith('post_')
class EventManager:
	def __init__(self):
		self.__handlers = {name:set() for name in VALID_EVENTS}

	def emit(self, symbol, *args):
		for func in self.__handlers[symbol]:
			func(*args)

	def add_listeners_from(self, obj):
		for attr in dir(obj):
			# eagerly assume that a handler-resembling function is one;
			#  a KeyError beats unintentionally dead code!
			if looks_like_handler(attr):
				self.__handlers[attr].add(getattr(obj,attr))

def flat(it):
	for x in it:
		yield from x

# Periodic hexagonal grid, stored in axial coords.
class Grid:
	def __init__(self, dim):
		self.dim = dim
		assert len(self.dim) == 2

	def nodes(self):
		''' Iterate over all nodes. '''
		return itertools.product(*(range(d) for d in self.dim))

	def neighbors(self, node):
		''' The six neighbors of a node on a hexagonal lattice. '''
		return self.rotations_around(node, [-1, 0, 1])

	def trefoil_neighbors(self, node):
		''' The six nodes with which a node can form a trefoil defect.

		For one to actually form, three nodes must all mutually be
		trefoil neighbors. '''
		return self.rotations_around(node, [2, -2, 0])

	def nodes_in_distance_range(self, nodes, mindist, maxdist):
		'''
		Collect nodes in a range of distances from a set of nodes.

		Collects nodes at a distance from ``mindist`` to ``maxdist``, inclusive.
		The input nodes have distance 0, their neighbors (excluding themselves)
		are distance 1, et cetera.

		Designed for functions which need to invalidate a region of the grid
		after making several modifications.
		'''
		# structured to avoid unnecessarily computing an extra group
		if maxdist < mindist: return
		for (n,group) in enumerate(bfs_groups_by_distance(nodes, self.neighbors)):
			if n < mindist: continue
			yield from group
			if n >= maxdist: break

	def rotations_around(self, node, disp):
		''' Get the node at node+disp, together with the other 5 nodes
		related to it by the sixfold rotational symmetry around node. '''
		a,b = node
		for da, db, _ in hex.cubic_rotations_60(*disp):
			yield self.reduce((a + da, b + db))

	def can_form_trefoil(self, nodes):
		''' Determine if the three given nodes can form a trefoil defect. '''
		n1,n2,n3 = nodes
		return all(
			u in self.trefoil_neighbors(v)
			for (u,v) in [(n1,n2), (n2,n3), (n3,n1)]
		)

	def reduce(self, node):
		''' Apply PBC to get a node's image in the unit cell. '''
		a, b = node
		return (a % self.dim[0], b % self.dim[1])


def bfs_groups_by_distance(roots, edge_func):
	seen = set()
	current = set(roots)
	while True:
		yield current
		seen |= current
		prev = current

		current = set()
		for x in prev:
			new = set(edge_func(x))
			new -= seen
			current.update(new)

