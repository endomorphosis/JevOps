import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat


theorem numina_atf_480756 : ∃ (a b : ℤ), Even a ∧ Even b ∧ a + b = 42 ∧ b = a + 2 ∧ b^2 - a^2 = 84 := by 
  have h_main : ∃ (a b : ℤ), Even a ∧ Even b ∧ a + b = 42 ∧ b = a + 2 ∧ b^2 - a^2 = 84 := by
    use 20, 22
    constructor
    · 
      exact even_iff_two_dvd.mpr (by norm_num)
    constructor
    · 
      exact even_iff_two_dvd.mpr (by norm_num)
    constructor
    · 
      norm_num
    constructor
    · 
      norm_num
    · 
      norm_num
  exact h_main