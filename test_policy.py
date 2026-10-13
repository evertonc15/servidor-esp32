import unittest

from agente_hardware import aprender, decidir


class PolicyTests(unittest.TestCase):
    def test_hot_dry_reactive_and_independent_actuators(self):
        decision = decidir({'temperatura': 30, 'umidade': 30, 'nivel': 1},
                           {'ventilador': False, 'umidificador': False}, modo='reativo')
        self.assertTrue(all(item['alterar'] and item['ligado'] for item in decision['propostas']))

    def test_learning_rejection_changes_choice_approval_strengthens(self):
        readings = {'temperatura': 30, 'umidade': 55, 'nivel': 1}
        states = {'ventilador': False, 'umidificador': False}
        baseline = decidir(readings, states)
        fan = baseline['propostas'][0]
        self.assertTrue(fan['ligado'])
        key = fan['preferencia_chave']
        preferences = {}
        for _ in range(3):
            learned = aprender(preferences, key, False)
            preferences[key] = learned['preferencia_atual']
        rejected = decidir(readings, states, preferences)
        self.assertFalse(rejected['propostas'][0]['ligado'])
        self.assertTrue(rejected['adaptado'])
        approved = aprender({}, key, True)
        strengthened = decidir(readings, states, {key: approved['preferencia_atual']})
        score_before = next(item for item in fan['alternativas'] if item['ligado'])['pontuacao_total']
        score_after = next(item for item in strengthened['propostas'][0]['alternativas'] if item['ligado'])['pontuacao_total']
        self.assertGreater(score_after, score_before)

    def test_priority_cannot_be_overridden(self):
        readings = {'temperatura': 33, 'umidade': 90, 'nivel': 0}
        states = {'ventilador': False, 'umidificador': True}
        decision = decidir(readings, states)
        preferences = {option['preferencia_chave']: (3 if not option['elegivel'] else -3)
                       for item in decision['propostas'] for option in item['alternativas']}
        adapted = decidir(readings, states, preferences)
        self.assertTrue(adapted['propostas'][0]['ligado'])
        self.assertFalse(adapted['propostas'][1]['ligado'])
        self.assertFalse(adapted['adaptado'])

    def test_unknown_does_not_send_and_same_state_does_not_repeat(self):
        readings = {'temperatura': 30, 'umidade': 30, 'nivel': 1}
        unknown = decidir(readings, {'ventilador': None, 'umidificador': None})
        self.assertTrue(all(item['bloqueado'] and not item['alterar'] for item in unknown['propostas']))
        same = decidir(readings, {'ventilador': True, 'umidificador': True})
        self.assertTrue(all(not item['alterar'] for item in same['propostas']))

    def test_hysteresis_and_feedback_bounds(self):
        readings = {'temperatura': 24, 'umidade': 45, 'nivel': 1}
        decision = decidir(readings, {'ventilador': True, 'umidificador': False})
        self.assertTrue(decision['propostas'][0]['ligado'])
        self.assertFalse(decision['propostas'][1]['ligado'])
        key = decision['propostas'][0]['preferencia_chave']
        self.assertEqual(aprender({key: -3}, key, False)['delta'], 0)

    def test_invalid_observation(self):
        with self.assertRaises(ValueError):
            decidir({'temperatura': float('nan'), 'umidade': 45, 'nivel': 1}, {})


if __name__ == '__main__':
    unittest.main()
