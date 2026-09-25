import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat


theorem numina_atf_522022 : 
  let total_phones : ℕ := 230
  let defective_phones : ℕ := 84
  let prob_both_defective : ℝ := (defective_phones : ℝ) / (total_phones : ℝ) * ((defective_phones : ℝ) - 1) / ((total_phones : ℝ) - 1)
  abs (prob_both_defective - 0.1324) < 0.0001 := by 
  intro total_phones defective_phones prob_both_defective
  have h₀ : prob_both_defective = (84 : ℝ) / 230 * (83 : ℝ) / 229 := by
    dsimp only [prob_both_defective, total_phones, defective_phones]
    norm_num
    <;> ring_nf
    <;> norm_num
    <;> field_simp
    <;> ring_nf
    <;> norm_num
  have h₁ : abs (prob_both_defective - 0.1324 : ℝ) < 0.0001 := by
    rw [h₀]
    have h₂ : abs (( (84 : ℝ) / 230 * (83 : ℝ) / 229 : ℝ) - 0.1324 : ℝ) < 0.0001 := by
      norm_num [abs_lt]
      <;>
      (try norm_num) <;>
      (try linarith) <;>
      (try ring_nf at *) <;>
      (try norm_num at *) <;>
      (try linarith)
    exact h₂
  exact h₁