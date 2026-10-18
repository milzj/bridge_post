"""Solver settings for the current Firedrake bridge example."""
filter_parameters = {
    'mat_type': 'aij', 'ksp_type': 'cg', 'ksp_rtol': 1e-12,
    'ksp_atol': 1e-14, 'ksp_max_it': 1000,
    'ksp_error_if_not_converged': True, 'pc_type': 'hypre',
    'pc_hypre_type': 'boomeramg',
}


def elasticity_parameters(solver):
    if solver == 'direct':
        return {'mat_type': 'aij', 'ksp_type': 'preonly', 'pc_type': 'lu',
                'pc_factor_mat_solver_type': 'mumps', 'ksp_error_if_not_converged': True}
    # With very soft void cells GAMG can become indefinite. FGMRES remains
    # valid for this preconditioner, whereas CG rejects such intermediate PCs.
    return {'mat_type': 'aij', 'ksp_type': 'fgmres', 'ksp_gmres_restart': 100,
            'ksp_rtol': 1e-10,
            'ksp_atol': 1e-13, 'ksp_max_it': 1000,
            'ksp_error_if_not_converged': True, 'pc_type': 'gamg',
            'pc_gamg_type': 'agg', 'pc_gamg_agg_nsmooths': 1,
            'pc_gamg_threshold': .01, 'mg_levels_ksp_type': 'chebyshev',
            'mg_levels_pc_type': 'jacobi', 'mg_levels_ksp_max_it': 3}
