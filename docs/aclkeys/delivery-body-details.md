Exact additional raw-byte differences in the saved object audit.

Each body below has different raw bytes but identical normalized bytes and resolved
targets. The differences are address displacements in ACL objects after code movement,
including assembler-resolved same-section calls. No instruction or target-identity
change is admitted by this classification. These 54 bodies are additional to the
21 canonical differences and six new-object bodies listed in the delivery report.

| Object | Exact symbol | Reason |
|---|---|---|
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_113acl_reply_logERNS_2OpE` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_114acl_parse_fileERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEERSt6vectorINS0_12AclUserImageESaISA_EERS6_.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_115acl_apply_rulesERNS0_12AclUserImageERKSt6vectorINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESaIS9_EEmRS9_PS9_.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_116acl_reply_deniedERNS_6ClientERNS_2OpEjNS_15AclDeniedReasonEjRNS_9ThreadCtxENS_13AclLogContextE.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_117acl_create_lockedEONS0_12AclUserImageEj` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_117acl_join_patternsERKNS_11AclSelectorEb` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_118acl_describe_imageERKNS0_12AclUserImageE` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_120acl_check_permissionIZNS_16acl_check_queuedEjRKNS_11CommandSpecERKSt6vectorINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESaISB_EEPjEUljE_EENS_15AclDeniedReasonEjS4_jOT_SG_` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_120acl_check_permissionIZNS_18acl_dispatch_entryERNS_6IoLoopERNS_6ClientERNS_2OpEjhEUljE_EENS_15AclDeniedReasonEjRKNS_11CommandSpecEjOT_Pj.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_120acl_check_permissionIZNS_20acl_recheck_blockingERNS_6ClientERNS_2OpERNS_9ThreadCtxEEUljE_EENS_15AclDeniedReasonEjRKNS_11CommandSpecEjOT_Pj.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_121acl_describe_commandsERKNS_11AclSelectorE` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_122acl_apply_command_ruleERNS_11AclSelectorENS_5SliceERNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEb.isra.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_123acl_sorted_users_lockedEv` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db012_GLOBAL__N_124acl_commit_images_lockedERSt6vectorINS0_12AclUserImageESaIS2_EEPNS_6IoLoopE` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db014acl_initializeERNS_6ServerERKNS_6ConfigERNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db014acl_log_denialERNS_9ThreadCtxERKNS_6ClientENS_15AclDeniedReasonENS_13AclLogContextENS_5SliceES7_` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db016acl_check_queuedEjRKNS_11CommandSpecERKSt6vectorINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESaIS9_EEPj` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db017acl_command_entryERNS_6IoLoopERNS_6ClientERNS_2OpE` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db018acl_dispatch_entryERNS_6IoLoopERNS_6ClientERNS_2OpEjh` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db020acl_recheck_blockingERNS_6ClientERNS_2OpERNS_9ThreadCtxE` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db023acl_channel_allowed_anyERKNS_7AclPermENS_5SliceEb` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZN8tomo_db024acl_pubsub_channel_entryERNS_6ClientERNS_2OpEbRNS_9ThreadCtxE` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZSt10__pop_heapIN9__gnu_cxx17__normal_iteratorIPN8tomo_db012_GLOBAL__N_111AclLogEntryESt6vectorIS4_SaIS4_EEEENS0_5__ops15_Iter_comp_iterIZNS3_13acl_reply_logERNS2_2OpEEUlRKS4_SF_E_EEEvT_SI_SI_RT0_` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZSt16__insertion_sortIN9__gnu_cxx17__normal_iteratorIPN8tomo_db012_GLOBAL__N_111AclLogEntryESt6vectorIS4_SaIS4_EEEENS0_5__ops15_Iter_comp_iterIZNS3_13acl_reply_logERNS2_2OpEEUlRKS4_SF_E_EEEvT_SI_T0_.isra.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZSt16__introsort_loopIN9__gnu_cxx17__normal_iteratorIPN8tomo_db012_GLOBAL__N_111AclLogEntryESt6vectorIS4_SaIS4_EEEElNS0_5__ops15_Iter_comp_iterIZNS3_13acl_reply_logERNS2_2OpEEUlRKS4_SF_E_EEEvT_SI_T0_T1_` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZSt16__introsort_loopIN9__gnu_cxx17__normal_iteratorIPPKN8tomo_db015CommandMetadataESt6vectorIS5_SaIS5_EEEElNS0_5__ops15_Iter_comp_iterIZNS2_12_GLOBAL__N_118acl_reply_categoryERNS2_2OpEEUlS5_S5_E_EEEvT_SI_T0_T1_` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZSt16__introsort_loopIN9__gnu_cxx17__normal_iteratorIPPN8tomo_db07AclUserESt6vectorIS4_SaIS4_EEEElNS0_5__ops15_Iter_comp_iterIZNS2_12_GLOBAL__N_123acl_sorted_users_lockedEvEUlPKS3_SE_E_EEEvT_SH_T0_T1_` | Address-displacement changes only; raw_equal=false, equal=true |
| `db0/src/cmd/acl.o` | `_ZSt4swapIN8tomo_db012_GLOBAL__N_111AclLogEntryEENSt9enable_ifIXsrSt6__and_IJSt6__not_ISt15__is_tuple_likeIT_EESt21is_move_constructibleIS7_ESt18is_move_assignableIS7_EEE5valueEvE4typeERS7_SH_` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_113acl_reply_logERNS_2OpE` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_114acl_parse_fileERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEERSt6vectorINS0_12AclUserImageESaISA_EERS6_.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_115acl_apply_rulesERNS0_12AclUserImageERKSt6vectorINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESaIS9_EEmRS9_PS9_.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_116acl_reply_deniedERNS_6ClientERNS_2OpEjNS_15AclDeniedReasonEjRNS_9ThreadCtxENS_13AclLogContextE.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_117acl_create_lockedEONS0_12AclUserImageEj` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_117acl_join_patternsERKNS_11AclSelectorEb` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_118acl_describe_imageERKNS0_12AclUserImageE` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_120acl_check_permissionIZNS_16acl_check_queuedEjRKNS_11CommandSpecERKSt6vectorINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESaISB_EEPjEUljE_EENS_15AclDeniedReasonEjS4_jOT_SG_` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_120acl_check_permissionIZNS_18acl_dispatch_entryERNS_6IoLoopERNS_6ClientERNS_2OpEjhEUljE_EENS_15AclDeniedReasonEjRKNS_11CommandSpecEjOT_Pj.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_120acl_check_permissionIZNS_20acl_recheck_blockingERNS_6ClientERNS_2OpERNS_9ThreadCtxEEUljE_EENS_15AclDeniedReasonEjRKNS_11CommandSpecEjOT_Pj.constprop.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_121acl_describe_commandsERKNS_11AclSelectorE` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_123acl_sorted_users_lockedEv` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo12_GLOBAL__N_124acl_commit_images_lockedERSt6vectorINS0_12AclUserImageESaIS2_EEPNS_6IoLoopE` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo14acl_initializeERNS_6ServerERKNS_6ConfigERNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo14acl_log_denialERNS_9ThreadCtxERKNS_6ClientENS_15AclDeniedReasonENS_13AclLogContextENS_5SliceES7_` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo16acl_check_queuedEjRKNS_11CommandSpecERKSt6vectorINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESaIS9_EEPj` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo18acl_dispatch_entryERNS_6IoLoopERNS_6ClientERNS_2OpEjh` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo20acl_recheck_blockingERNS_6ClientERNS_2OpERNS_9ThreadCtxE` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo23acl_channel_allowed_anyERKNS_7AclPermENS_5SliceEb` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZN4tomo24acl_pubsub_channel_entryERNS_6ClientERNS_2OpEbRNS_9ThreadCtxE` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZSt10__pop_heapIN9__gnu_cxx17__normal_iteratorIPN4tomo12_GLOBAL__N_111AclLogEntryESt6vectorIS4_SaIS4_EEEENS0_5__ops15_Iter_comp_iterIZNS3_13acl_reply_logERNS2_2OpEEUlRKS4_SF_E_EEEvT_SI_SI_RT0_` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZSt13__adjust_heapIN9__gnu_cxx17__normal_iteratorIPN4tomo12_GLOBAL__N_111AclLogEntryESt6vectorIS4_SaIS4_EEEElS4_NS0_5__ops15_Iter_comp_iterIZNS3_13acl_reply_logERNS2_2OpEEUlRKS4_SF_E_EEEvT_T0_SJ_T1_T2_.isra.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZSt16__insertion_sortIN9__gnu_cxx17__normal_iteratorIPN4tomo12_GLOBAL__N_111AclLogEntryESt6vectorIS4_SaIS4_EEEENS0_5__ops15_Iter_comp_iterIZNS3_13acl_reply_logERNS2_2OpEEUlRKS4_SF_E_EEEvT_SI_T0_.isra.0` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZSt16__introsort_loopIN9__gnu_cxx17__normal_iteratorIPN4tomo12_GLOBAL__N_111AclLogEntryESt6vectorIS4_SaIS4_EEEElNS0_5__ops15_Iter_comp_iterIZNS3_13acl_reply_logERNS2_2OpEEUlRKS4_SF_E_EEEvT_SI_T0_T1_` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZSt16__introsort_loopIN9__gnu_cxx17__normal_iteratorIPPKN4tomo15CommandMetadataESt6vectorIS5_SaIS5_EEEElNS0_5__ops15_Iter_comp_iterIZNS2_12_GLOBAL__N_118acl_reply_categoryERNS2_2OpEEUlS5_S5_E_EEEvT_SI_T0_T1_` | Address-displacement changes only; raw_equal=false, equal=true |
| `src/cmd/acl.o` | `_ZSt16__introsort_loopIN9__gnu_cxx17__normal_iteratorIPPN4tomo7AclUserESt6vectorIS4_SaIS4_EEEElNS0_5__ops15_Iter_comp_iterIZNS2_12_GLOBAL__N_123acl_sorted_users_lockedEvEUlPKS3_SE_E_EEEvT_SH_T0_T1_` | Address-displacement changes only; raw_equal=false, equal=true |
