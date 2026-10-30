"""Retained historical math witnesses, not evidence that a teaching judge is calibrated."""

import math
import unittest


class RealAnswerMathWitnessTests(unittest.TestCase):
    def test_derivative_product_is_not_the_product_function_derivative(self):
        # candidate/assistance-two-turns/answer.md misidentifies this as the
        # derivative of sin(x)*x**2. Check by an independent finite difference.
        x, h = 1.0, 1e-5
        product = lambda t: math.sin(t) * t**2
        measured = (product(x + h) - product(x - h)) / (2 * h)
        correct = x**2 * math.cos(x) + 2 * x * math.sin(x)
        claimed = 2 * x * math.cos(x)
        self.assertAlmostEqual(measured, correct, places=8)
        self.assertGreater(abs(measured - claimed), 1)

    def test_zero_derivative_does_not_mean_zero_finite_change(self):
        # candidate flashcard 5 says even large Delta x gives Delta u approx 0.
        x, h = 0, 1
        delta_u = (x + h)**2 - x**2
        self.assertEqual(delta_u, 1)
        self.assertGreater(math.sin((x + h)**2) - math.sin(x**2), 0.8)
        # Preserve the valid local intuition instead of banning approximations.
        self.assertLess(abs(math.sin(1e-4**2) / 1e-4), 1.01e-4)

    def test_increment_of_x_is_not_increment_of_u(self):
        # candidate flashcard 4 writes u+h=(x+h)**2 with u=x**2.
        x, h = 1, 0.1
        u = x**2
        self.assertNotAlmostEqual(u + h, (x + h)**2)
        delta_u = 2 * x * h + h**2
        self.assertAlmostEqual(u + delta_u, (x + h)**2)

    def test_real_good_answer_finite_difference_is_not_a_contradiction(self):
        # baseline flashcards: 1.079 is a finite difference, 1.081 the derivative.
        h = 0.001
        measured = (math.sin((1 + h)**2) - math.sin(1)) / h
        derivative = 2 * math.cos(1)
        self.assertEqual(round(measured, 3), 1.079)
        self.assertEqual(round(derivative, 3), 1.081)
        smaller = (math.sin((1 + h / 10)**2) - math.sin(1)) / (h / 10)
        self.assertLess(abs(smaller - derivative), abs(measured - derivative))

    def test_defined_intermediate_and_reordered_factors_are_equivalent(self):
        for x in (-2, -0.3, 0, 0.5, 1, 2):
            u = x**2
            self.assertEqual(2 * x * math.cos(u), math.cos(x**2) * 2 * x)


if __name__ == "__main__":
    unittest.main()
