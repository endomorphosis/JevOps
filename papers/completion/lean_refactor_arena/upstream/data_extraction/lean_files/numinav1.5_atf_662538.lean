import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat


theorem numina_atf_662538 : 
  (25 : ℚ) / (25 + 50) * 100 = 100 / 3 ∧ 
  abs ((100 / 3 : ℝ) - 33.33) < 0.01 := by 
  have h₁ : (25 : ℚ) / (25 + 50) * 100 = 100 / 3 := by
    norm_num [div_eq_mul_inv, mul_assoc]
    <;> field_simp
    <;> ring_nf
    <;> norm_num
    <;> rfl
  have h₂ : abs ((100 / 3 : ℝ) - 33.33) < 0.01 := by
    norm_num [abs_lt, sub_lt_iff_lt_add, sub_add_eq_add_sub]
    <;>
    (try norm_num) <;>
    (try linarith) <;>
    (try
      {
        norm_num at *
        <;>
        linarith
      })
    <;>
    (try
      {
        norm_num [abs_of_pos, abs_of_nonneg] at *
        <;>
        linarith
      })
  exact ⟨h₁, h₂⟩