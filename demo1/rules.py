from .sim import Rule
from .sim import DEFAULT_KIND
from .state import STATUS_NO_VACANCY, STATUS_DIVACANCY, STATUS_TREFOIL_PARTICIPANT

# A (likely temporary) intermediate class which abstracts out a very
# common pattern seen among the implementation of the rules.
class InvalidationBasedRule(Rule):
	def moves_dependent_on(self, state, nodes):
		''' Get a list of moves present in the current board whose existence
		depends on the status of at least one of the given nodes. '''
		raise NotImplementedError

	def initialize_moves(self, state):
		for move in self.moves_dependent_on(state, state.grid.nodes()):
			self.add_move(move)
	def pre_status_change(self, state, nodes):
		for move in self.moves_dependent_on(state, nodes):
			self.clear_move(move)
	def post_status_change(self, state, nodes):
		for move in self.moves_dependent_on(state, nodes):
			self.add_move(move)

#-------------------------------------------------------------------------

class RuleCreateVacancy(InvalidationBasedRule):
	def perform(self, node, state):
		state.new_vacancy(node)

	def nodes_affected_by(self, node):
		return [node]

	def info(self, node):
		return { 'node': node }

	def moves_dependent_on(self, state, nodes):
		return [x for x in nodes if state.node_status(x) is STATUS_NO_VACANCY]

class RuleFillVacancy(InvalidationBasedRule):
	def perform(self, node, state):
		state.pop_vacancy(node)

	def nodes_affected_by(self, node):
		return [node]

	def info(self, node):
		return { 'node': node }

	def moves_dependent_on(self, state, nodes):
		return [x for x in nodes if state.node_status(x) is STATUS_DIVACANCY]

class RuleMoveVacancy(InvalidationBasedRule):
	def perform(self, move, state):
		(old,new) = move
		state.pop_vacancy(old)
		state.new_vacancy(new)

	def nodes_affected_by(self, move):
		return move # (old, new)

	def info(self, move):
		(old,new) = move
		return { 'was': old, 'now': new }

	def kinds(self):
		return [DEFAULT_KIND]

	def moves_dependent_on(self, state, nodes):
		for n in state.grid.nodes_in_distance_range(nodes, 0, 1):
			yield from self.moves_from_node(state, n)

	# override to avoid an unnecessary bfs
	def initialize_moves(self, state):
		for node in state.grid.nodes():
			for move in self.moves_from_node(state, node):
				self.add_move(move)

	def moves_from_node(self, state, node):
		if state.node_status(node) is STATUS_DIVACANCY:
			for nbr in state.grid.neighbors(node):
				if state.node_status(nbr) is STATUS_NO_VACANCY:
					yield (node, nbr)

class RuleCreateTrefoil(InvalidationBasedRule):
	''' Allows 3 divacancies to rotate into a trefoil defect. '''
	def perform(self, nodes, state):
		for node in nodes:
			state.pop_vacancy(node)
		state.new_trefoil(nodes)

	def nodes_affected_by(self, nodes):
		return nodes

	def info(self, nodes):
		return { 'nodes': list(nodes) }

	def moves_dependent_on(self, state, nodes):
		from itertools import combinations

		def inner(nodes):
			def can_become_trefoil(node):
				return state.node_status(node) == STATUS_DIVACANCY

			# find trefoil-ready groups in which at least one vertex was invalidated
			nodes = list(filter(can_become_trefoil, nodes))
			for node1 in nodes:
				neighbors = state.grid.trefoil_neighbors(node1)
				neighbors = list(filter(can_become_trefoil, neighbors))
				for node2, node3 in combinations(neighbors, r=2):
					if node2 in state.grid.trefoil_neighbors(node3):
						yield frozenset([node1,node2,node3])

		# There may be duplicates; cull them.
		return set(inner(nodes)).__iter__()

class RuleDestroyTrefoil(InvalidationBasedRule):
	''' Allows a trefoil to rotate back into 3 garden-variety divacancies. '''
	def perform(self, nodes, state):
		state.pop_trefoil(nodes)
		for node in nodes:
			state.new_vacancy(node)

	def nodes_affected_by(self, nodes):
		return nodes

	def info(self, nodes): return { 'nodes': list(nodes) }

	def moves_dependent_on(self, state, nodes):
		# find trefoils for which at least one vertex was invalidated
		remaining = {x for x in nodes if state.node_status(x) is STATUS_TREFOIL_PARTICIPANT}
		while remaining:
			trefoil_nodes = frozenset(state.trefoil_nodes_at(remaining.pop()))
			remaining -= trefoil_nodes # skip dupes
			yield trefoil_nodes

