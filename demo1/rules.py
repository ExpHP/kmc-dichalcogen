from .sim import Rule
from .sim import DEFAULT_KIND
from .state import BOTH_LAYERS

# A (likely temporary) intermediate class which abstracts out a very
# common pattern seen among the implementation of the rules.
class OneKindRule(Rule):
	def moves_dependent_on(self, state, nodes):
		''' Get a list of moves present in the current board whose existence
		depends on the status of at least one of the given nodes. '''
		raise NotImplementedError
	def all_moves(self, state):
		''' Get all moves present in the current board.

		Ideally, the implementation should look "obviously correct"; at least more so
		perhaps than ``moves_dependent_on``. It is used for validation purposes. '''
		raise NotImplementedError

	def initialize_moves(self, state):
		for move in self.all_moves(state):
			self.add_move(move)
	def pre_status_change(self, state, nodes):
		for move in self.moves_dependent_on(state, nodes):
			self.clear_move(move)
	def post_status_change(self, state, nodes):
		for move in self.moves_dependent_on(state, nodes):
			self.add_move(move)

# FIXME A HACK because I apparently forgot when writing the above
#       that some rules have kinds!
class MultiKindRule(Rule):
	def moves_dependent_on(self, state, nodes):
		''' Get a list of (move,kind)s present in the current board whose existence
		depends on the status of at least one of the given nodes. '''
		raise NotImplementedError
	def all_moves(self, state):
		''' Get all (move,kind)s present in the current board.

		Ideally, the implementation should look "obviously correct"; at least more so
		perhaps than ``moves_dependent_on``. It is used for validation purposes. '''
		raise NotImplementedError

	def initialize_moves(self, state):
		for move,kind in self.all_moves(state):
			self.add_move(move,kind)
	def pre_status_change(self, state, nodes):
		for move,kind in self.moves_dependent_on(state, nodes):
			self.clear_move(move)
	def post_status_change(self, state, nodes):
		for move,kind in self.moves_dependent_on(state, nodes):
			self.add_move(move,kind)

#-------------------------------------------------------------------------

# NOTE: Frequently two rules which are "inverses" of each other have a lot of
#       similarities in their implementation.  In some cases the rules are small
#       enough that they're still easy enough to maintain; in other cases the
#       similar bits may be "rehacktored" out into an intermediate class.

class RuleCreateDivacancy(OneKindRule):
	''' Permit a pristine chalcogen pair to turn directly into a divacancy. '''
	def perform(self, node, state):
		state.new_divacancy(node)

	def nodes_affected_by(self, node):
		return [node]

	def info(self, node):
		return { 'node': node }

	def all_moves(self, state):
		return state.pristine_nodes()

	def moves_dependent_on(self, state, nodes):
		return filter(state.is_pristine, nodes)

class RuleFillDivacancy(OneKindRule):
	''' Permit a divacancy to be completely filled in one step. '''
	def perform(self, node, state):
		state.pop_divacancy(node)

	def nodes_affected_by(self, node):
		return [node]

	def info(self, node):
		return { 'node': node }

	def all_moves(self, state):
		return (vacancy.node for vacancy in state.divacancies())

	def moves_dependent_on(self, state, nodes):
		return filter(state.is_divacancy, nodes)

class RuleMoveDivacancy(MultiKindRule):
	''' Permit migration of a divacancy (as a single unit). '''
	def perform(self, move, state):
		(old,new) = move
		state.pop_divacancy(old)
		state.new_divacancy(new)

	def nodes_affected_by(self, move):
		return move # (old, new)

	def info(self, move):
		(old,new) = move
		return { 'was': old, 'now': new }

	def kinds(self):
		return list(self.KINDS)

	def all_moves(self, state):
		for x in state.divacancies():
			yield from self.moves_from_node(state, x.node)

	def moves_dependent_on(self, state, nodes):
		for node in state.grid.nodes_in_distance_range(nodes, 0, 1):
			yield from self.moves_from_node(state, node)

	def moves_from_node(self, state, node):
		if state.is_divacancy(node):
			for (nbr,near,far) in state.grid.neighbors_and_mutuals(node):
				if state.is_pristine(nbr):
					kind = self.move_kind(state, near, far)
					yield ((node, nbr), kind)

	# Organized according to a code:
	KINDS = [
		'natural',
		'missing-metal', # "left to up right"
		'missing-comb',  # "left to down right"
		'missing-both',  # combination thereof
	]
	def move_kind(self, state, near, far):
		return self.KINDS[
			int(state.is_divacancy(near)) + 2*int(state.is_divacancy(far))
		]


#-------------------------------------------------------------------------

class RuleCreateTrefoil(OneKindRule):
	''' Permit 3 divacancies to rotate into a trefoil defect. '''
	def perform(self, nodes, state):
		for node in nodes:
			state.pop_divacancy(node)
		state.new_trefoil(nodes)

	def nodes_affected_by(self, nodes):
		return nodes

	def info(self, nodes):
		return { 'nodes': list(nodes) }

	def all_moves(self, state):
		# // lazy :f
		nodes = [x.node for x in state.divacancies()]
		return self.moves_dependent_on(state, nodes)

	def moves_dependent_on(self, state, nodes):
		from itertools import combinations

		def inner(nodes):
			can_become_trefoil = state.is_divacancy

			# find trefoil-ready groups in which at least one vertex was invalidated
			for node1 in filter(can_become_trefoil, nodes):
				neighbors = state.grid.trefoil_neighbors(node1)
				neighbors = list(filter(can_become_trefoil, neighbors))
				for node2, node3 in combinations(neighbors, r=2):
					if node2 in state.grid.trefoil_neighbors(node3):
						yield frozenset([node1,node2,node3])

		# There may be duplicates; cull them.
		return set(inner(nodes)).__iter__()

class RuleDestroyTrefoil(OneKindRule):
	''' Permit a trefoil to rotate back into 3 divacancies. '''
	def perform(self, nodes, state):
		state.pop_trefoil(nodes)
		for node in nodes:
			state.new_divacancy(node)

	def nodes_affected_by(self, nodes):
		return nodes

	def info(self, nodes):
		return { 'nodes': list(nodes) }

	def all_moves(self, state):
		return [x.nodes for x in state.trefoils()]

	def moves_dependent_on(self, state, nodes):
		# find trefoils for which at least one vertex was invalidated
		remaining = set(filter(state.is_trefoil, nodes))
		while remaining:
			trefoil_nodes = frozenset(state.trefoil_nodes_at(remaining.pop()))
			remaining -= trefoil_nodes # skip dupes
			yield trefoil_nodes

#-------------------------------------------------------------------------

# Common attributes for Create/FillMonovacancy
class __Rule__Monovacancy(MultiKindRule):
	def perform(self, move, state):
		node, layer, layerset = move
		assert (layerset != state.vacant_layerset_at(node)), "no-op in move-list!"
		if state.is_vacancy(node):
			state.pop_vacancy(node)
		if layerset != 0:
			state.new_vacancy(node, layerset)

	def nodes_affected_by(self, move):
		node, layer, layerset = move
		return [node]

	def info(self, move):
		node, layer, layerset = move
		return { 'node': node, 'layer': layer }

	def moves_dependent_on(self, state, nodes):
		for node in filter(state.has_defined_layerset, nodes):
			kind = self.getkind(state, node)
			old_layerset = state.vacant_layerset_at(node)
			for layer in [1,2]:
				new_layerset = self.new_layerset(old_layerset, layer)
				if new_layerset != old_layerset:
					yield ((node, layer, new_layerset), kind)

	def getkind(self, state, node):     raise NotImplementedError
	def new_layerset(self, layerset, layer): raise NotImplementedError

# Kinds are named to make the inverse relationships clear;
# CreateMonovacancy:from-double is the inverse of FillMonovacancy:make-double
#
# The names are unambiguous (or at least, there's only one valid interpretation
#  given which kinds belong to which rule, which is that "double" and "empty"
#  refer to number of chalcogens present)
class RuleCreateMonovacancy(__Rule__Monovacancy):
	''' Permit a single chalcogen to be ejected from any site. '''
	def kinds(self):
		return ['from-double', 'make-empty']
	def getkind(self, state, node):
		return 'from-double' if state.is_pristine(node) else 'make-empty'
	def new_layerset(self, layers, layer):
		return layers | layer

	def all_moves(self, state):
		for node in state.pristine_nodes():
			# introduce a vacancy where there were none
			yield ((node, 1, 1), 'from-double')
			yield ((node, 2, 2), 'from-double')
		for x in state.monovacancies():
			# eject remaining layer
			layer = BOTH_LAYERS & ~x.layers
			yield ((x.node, layer, BOTH_LAYERS), 'make-empty')

class RuleFillMonovacancy(__Rule__Monovacancy):
	''' Permit a chalcogen to fill a single monovacancy. '''
	def kinds(self):
		return ['make-double', 'from-empty']
	def getkind(self, state, node):
		return 'from-empty' if state.is_divacancy(node) else 'make-double'
	def new_layerset(self, layers, layer):
		return layers & ~layer

	def all_moves(self, state):
		for x in state.divacancies():
			# remove a vacancy from a divacancy, leaving the other behind
			yield ((x.node, 1, 2), 'from-empty')
			yield ((x.node, 2, 1), 'from-empty')
		for x in state.monovacancies():
			# remove the only vacancy
			layer = x.layers
			yield ((x.node, layer, 0), 'make-double')


class RuleFlipMonovacancy(OneKindRule):
	''' Permit a monovacancy to move between layers. '''
	def perform(self, node, state):
		vacancy = state.pop_vacancy(node)
		state.new_vacancy(node, BOTH_LAYERS & ~vacancy.layers)

	def nodes_affected_by(self, node):
		return [node]

	def info(self, node):
		return { 'node': node }

	def all_moves(self, state):
		return (vacancy.node for vacancy in state.monovacancies())

	def moves_dependent_on(self, state, nodes):
		return filter(state.is_monovacancy, nodes)
