import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat


theorem numina_atf_640652 : ∃ (total : ℝ), 
  total = 5000 + 200 + 0.3 * total ∧ 
  abs (total - 7428.57) < 0.01 := by 
  have h_main : ∃ (total : ℝ), total = 5000 + 200 + 0.3 * total ∧ abs (total - 7428.57) < 0.01 := by
    use (52000 : ℝ) / 7
    constructor
    · 
      norm_num [div_eq_mul_inv, mul_assoc]
      <;> ring_nf at *
      <;> norm_num at *
      <;> linarith
    · 
      have h : abs (( (52000 : ℝ) / 7 : ℝ) - 7428.57) < 0.01 := by
        norm_num [abs_of_pos, abs_of_nonneg, sub_pos]
        <;>
        (try norm_num) <;>
        (try linarith) <;>
        (try ring_nf at *) <;>
        (try norm_num at *) <;>
        (try linarith)
      exact h
  exact h_main