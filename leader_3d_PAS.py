"""
Builds PAS schedules from SAS records and candidate trials
- Output: PAS schedule and execution.
"""

class PASLeaderAlgorithm:
    """
    Coordinates PAS candidate evaluation and scheduling
    """

    def __init__(self, PASleader_env):
        self.PASleader_env = PASleader_env

    def _PASactivation_within_limit(self, PASentries, PASactivation, PASduration):
        """
        Checks concurrent activation capacity
        """
        PASlimit = self.PASleader_env.PASactive_limit()
        
        if PASlimit is None:
            return True

        PASarrival = PASactivation + PASduration
        PASevents = {}
        
        for PASentry in PASentries:
            PASoverlap_start = max(PASactivation, PASentry.PASactivation_time)
            PASoverlap_end = min(PASarrival, PASentry.PASarrival_time + 1)
            if PASoverlap_start >= PASoverlap_end:
                continue
            PASevents[PASoverlap_start] = PASevents.get(PASoverlap_start, 0) + 1
            PASevents[PASoverlap_end] = PASevents.get(PASoverlap_end, 0) - 1

        PASexisting_active = 0
        
        for PAStime in sorted(PASevents):
            PASexisting_active += PASevents[PAStime]
            # candidate 자신까지 더했을 때 limit를 넘으면 허용하지 않는다.
            if PASexisting_active + 1 > PASlimit:
                return False
        return True

    def _PASrespect_active_limit(self, PASentries, PASactivation, PASduration):
        """
        Shifts a start time until capacity is available.
        """
        PASoriginal_activation = PASactivation
        while not self._PASactivation_within_limit(
            PASentries, PASactivation, PASduration
        ):
            PASactivation += 1
        return PASactivation, PASactivation - PASoriginal_activation

    def PASleader_baseline(self):
        """
        Obtains SAS removal records.
        """
        return self.PASleader_env.PASrun_sas_baseline()

    def PASleader_prepare_engine(self, PASrecords, PASentries=()):
        """
        Restores approved state in an incremental scheduler.
        """
        from pas_incremental_scheduler import IncrementalPAS

        PASengine = IncrementalPAS(self.PASleader_env, PASrecords)
        PASengine.restore_approved(PASentries)
        
        return PASengine

    def PASleader_attempt(self, PASrecords, PASentries, PASpending=None, PASengine=None):
        """
        Evaluates one PAS scheduling candidate.
        """
        PASentries = tuple(PASentries)
        PASrecord_index = len(PASentries)
        
        if PASrecord_index >= len(PASrecords):
            return PASentries, None, 0
        
        if PASengine is None:
            PASengine = self.PASleader_prepare_engine(PASrecords, PASentries)
        
        PASrecord = PASrecords[PASrecord_index]

        if PASpending is None:
            PASactivation = (
                1 if PASrecord_index == 0 else
                PASentries[-1].PASarrival_time + 2 - PASrecord.PASduration
            )
            PASattempts = 0
        else:
            if PASpending['PASmodule_id'] != PASrecord.PASmodule_id:
                raise RuntimeError(
                    'PAS checkpoint pending module does not match next SAS record'
                )
            PASactivation = PASpending['PASactivation_time']
            PASattempts = PASpending['PASattempts']

        PASactivation, PAScapacity_shift = self._PASrespect_active_limit(PASentries, PASactivation, PASrecord.PASduration)
        
        if PAScapacity_shift:
            self.PASleader_env.PASreport_progress(
                f'PAS: active-limit shifted {PASrecord.PASmodule_id} by '
                f'{PAScapacity_shift} timestep(s)'
            )
        
        PAScandidate = self.PASleader_env.PASmake_entry(
            PASrecord.PASmodule_id,
            PASrecord.PASduration,
            PASactivation,
            PASactivation + PASrecord.PASduration - 1,
        )
        PASattempts += 1
        PAStraversal = PASengine.PASprepare_candidate(PASentries, PAScandidate)
        PASstatic_environment = PAStraversal['layout']
        PASreason = None
        PASstage1_ok = False
        PAStrial = None
        PASresult = None

        for PAStime in range(PASactivation, PAScandidate.PASarrival_time + 1):
            try:
                PASengine.PASapply_confirmed_activations(PASstatic_environment, PAStime)
                PASdirection = PASengine.PASnext_candidate_direction(PAStraversal)
                if PASdirection is None:
                    PASreason = f'candidate has no legal direction at t={PAStime}'
                    break
                PASrequired = PASengine.PAScandidate_required_cells(PAStraversal, PASdirection)
                PAScolliding_id = next((
                    PASother_id
                    for PASother_id, PASmove in PASengine.PASconfirmed_moves_at(PAStime).items()
                    if PASrequired & PASmove.required
                ), None)
                if PAScolliding_id is not None:
                    PASreason = (
                        f'F12 RequiredCells collision at t={PAStime}: '
                        f'{PASrecord.PASmodule_id} vs {PAScolliding_id}'
                    )
                    break
                PASposition = PASengine.PASadvance_candidate(PAStraversal, PASdirection)
                if PASposition in PASstatic_environment.grid.sinks:
                    if PASentries and PAStime <= PASentries[-1].PASarrival_time:
                        PASreason = 'candidate violated confirmed Sink-arrival order'
                    else:
                        PASstage1_ok = True
                    break
            except Exception as PASexc:
                PASreason = f'candidate traversal at t={PAStime}: {PASexc}'
                break
        
        else:
            PASreason = 'candidate exceeded SAS duration deadline'

        if PASstage1_ok:
            from simulator import PASSimulationResult

            PASschedule = PASentries + (PAScandidate,)
            PASsimulation = PASengine.PASrestore_configuration_before(PASschedule)
            PAStrial = PASengine.PASnew_trial(PAScandidate)
            PASold_ids = {PASentry.PASmodule_id for PASentry in PASentries}
            
            import os
            
            PASmax_steps = int(os.environ.get('PAS_MAX_STEPS', '1000000'))

            for _ in range(PASmax_steps):
                PAStime = PASsimulation.PAScurrent_time
                PASevent, _ = PASengine.PASexecute_simultaneous_step(PASsimulation)
                if PASevent == 'stuck':
                    PASreason = PASsimulation.simulator_error_msg or 'PAS step failed'
                    break
                PASobserved = PASengine.PASobserved_moves(PASsimulation)
                PASexpected_positions = {
                    PASmodule_id: PASmove.position
                    for PASmodule_id, PASmove in PASengine.PASconfirmed_moves_at(PAStime).items()
                    if PASmodule_id in PASold_ids
                }
                PASobserved_positions = {
                    PASmodule_id: PASmove.position
                    for PASmodule_id, PASmove in PASobserved.items()
                    if PASmodule_id in PASold_ids
                }
                if PASobserved_positions != PASexpected_positions:
                    PASreason = f'confirmed path changed at t={PAStime}'
                    break
                PASengine.PASrecord_trial_step(PAStrial, PASsimulation, PAStime)
                if PASsimulation.simulator_finished:
                    if PASsimulation.PASfinished_now() and not PASsimulation.simulator_error_msg:
                        PASengine.PASfinalize_trial(PAStrial, PASsimulation)
                        PASresult = PASSimulationResult(
                            True, dict(PASsimulation.PASarrival_times)
                        )
                    else:
                        PASreason = PASsimulation.simulator_error_msg or 'incomplete PAS'
                    break
            
            else:
                PASreason = f'PAS exceeded max steps {PASmax_steps}'
            
            if PASresult is None:
                PAStrial = None
                PASresult = PASSimulationResult(False, {}, PASreason)

        if PASresult is not None and PASresult.PASaccepted:
            PASactual_arrival = PASresult.PASarrival_times[PASrecord.PASmodule_id]
            if PASactual_arrival > PAScandidate.PASarrival_time:
                raise RuntimeError('PAS candidate accepted after its deadline')
            if PASentries and PASactual_arrival <= PASentries[-1].PASarrival_time:
                raise RuntimeError('PAS candidate accepted out of SAS sink-arrival order')
            for PASentry in PASentries:
                if PASresult.PASarrival_times.get(PASentry.PASmodule_id) != PASentry.PASarrival_time:
                    raise RuntimeError('PAS candidate changed confirmed sink-arrival time')
            PASconfirmed = self.PASleader_env.PASmake_entry(
                PASrecord.PASmodule_id,
                PASrecord.PASduration,
                PASactivation,
                PASactual_arrival,
            )
            PASengine.PAScommit_approved(PASconfirmed, PAStrial)
            self.PASleader_env.PASreport_progress(
                f'PAS: module {PASrecord_index + 1}/{len(PASrecords)} accepted on '
                f'attempt {PASattempts} ({PASattempts - 1} rejected)'
            )
            return PASentries + (PASconfirmed,), None, PASattempts

        if PASattempts >= self.PASleader_env.PAScandidate_limit():
            raise RuntimeError(
                'PAS could not find an accepted candidate for '
                f'{PASrecord.PASmodule_id} after {PASattempts} attempts; '
                f'last rejection={PASreason}'
            )

        return PASentries, {
            'PASmodule_id': PASrecord.PASmodule_id,
            'PASactivation_time': PASactivation + 1,
            'PASattempts': PASattempts,
        }, PASattempts

    def PASleader_extend(self, PASrecords, PASentries=(), PASmodule_limit=None, PASengine=None, PASon_accept=None,):
        """
        Adds accepted candidates in SAS order
        """
        PASrecords = tuple(PASrecords)
        PASentries = tuple(PASentries)
        
        if len(PASentries) > len(PASrecords):
            raise ValueError('PAS schedule has more entries than SAS records')
        
        PAStarget_count = len(PASrecords)
        
        if PASmodule_limit is not None:
            PAStarget_count = min(
                PAStarget_count, len(PASentries) + max(0, int(PASmodule_limit))
            )
        
        if PASengine is None:
            PASengine = self.PASleader_prepare_engine(PASrecords, PASentries)
        
        PASpending = None
        PASattempt_counts = {}
       
        while len(PASentries) < PAStarget_count:
            PASrecord_index = len(PASentries)
            PASentries, PASpending, PASattempts = self.PASleader_attempt(
                PASrecords, PASentries, PASpending, PASengine
            )
            if PASpending is None:
                if PASrecord_index > 0:
                    PASattempt_counts[PASrecords[PASrecord_index].PASmodule_id] = PASattempts
                if PASon_accept is not None:
                    # I/O는 Worker가 전달한 callback에서만 수행한다.
                    # 승인/후보 순회 자체는 이 Leader가 수행한다.
                    PASon_accept(PASentries, PASattempts)
            elif PASattempts % 100 == 0:
                self.PASleader_env.PASreport_progress(
                    f'PAS: scheduling {PASrecord_index + 1}/{len(PASrecords)}, '
                    f'candidate attempt {PASattempts}'
                )
        return PASentries, PASattempt_counts

    def PASleader_normalize(self, PASentries):
        """
        Shifts the schedule to start at time one
        """
        PASentries = tuple(PASentries)
        
        if not PASentries:
            return ()
        
        PASminimum = min(PASentry.PASactivation_time for PASentry in PASentries)
        
        return tuple(
            self.PASleader_env.PASmake_entry(
                PASentry.PASmodule_id,
                PASentry.PASduration,
                PASentry.PASactivation_time - PASminimum + 1,
                PASentry.PASarrival_time - PASminimum + 1,
            )
            for PASentry in PASentries
        )

    def PASleader_build(self):
        """
        Builds and normalizes the PAS schedule.
        """
        PASrecords = self.PASleader_baseline()
        PASengine = self.PASleader_prepare_engine(PASrecords)
        PASentries, PASattempt_counts = self.PASleader_extend(PASrecords, PASengine=PASengine)
        
        if tuple(PASentries) != PASengine.approved:
            raise RuntimeError('PAS leader and approved trajectories disagree')
        
        return self.PASleader_normalize(PASentries), PASattempt_counts

    def PASleader_execute(self, PASschedule=None, PAStrace_path=None):
        """
        Creates an execution for a fixed PAS schedule
        """
        if PASschedule is None:
            PASschedule, _PASattempt_counts = self.PASleader_build()

        return self.PASleader_env.PAScreate_execution(PASschedule, PAStrace_path)
