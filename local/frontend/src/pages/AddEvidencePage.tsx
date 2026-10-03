import { useEffect, useState } from 'react'
import {
  useFieldArray,
  useForm,
  type FieldErrors,
  type UseFormRegister,
} from 'react-hook-form'
import {
  Braces,
  CheckCircle2,
  ClipboardPlus,
  HardHat,
  Info,
  Link2,
  Paperclip,
  Plus,
  Settings2,
  Trash2,
  UserRound,
  Wrench,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  useIngestEvidence,
  type AttachmentMetadataInput,
  type ContextDimensionInput,
  type ContextQuality,
  type ContextSnapshotInput,
  type EvidenceIngestionInput,
  type EvidenceMode,
} from '../api/evidence'
import { ApiError } from '../api/http'
import { useCurrentMachine, useCurrentMachineComponents } from '../api/machines'
import {
  EmptyState,
  ErrorState,
  GlassCard,
  GlassPanel,
  LoadingSkeleton,
  SectionHeader,
  StatusBadge,
  TechnicalId,
} from '../components/primitives'
import { localInputToIso, machineIdentity, machineProduct, machineSite } from '../utils/machineFormatting'
import { PageIntro } from './PageIntro'

const CONTEXT_DIMENSIONS = ['shift', 'location', 'machine_operating_state', 'workload', 'environment'] as const
const QUALITY_VALUES: ContextQuality[] = ['KNOWN', 'UNKNOWN', 'STALE']

type ContextKey = typeof CONTEXT_DIMENSIONS[number]

type ContextDimensionForm = {
  value: string
  quality: ContextQuality
  freshness_basis: string
}

type AttachmentForm = {
  attachment_type: string
  storage_reference: string
  mime_type: string
  file_size: string
  checksum: string
  created_at: string
}

interface EvidenceFormValues {
  machine_id: string
  component_id: string
  original_source_record_id: string
  original_timestamp: string
  source_specific: string
  payload: string
  raw_payload: string
  provenance: string
  context_enabled: boolean
  context: Record<ContextKey, ContextDimensionForm>
  attachments: AttachmentForm[]
}

interface ModeConfig {
  mode: EvidenceMode
  title: string
  description: string
  specificLabel: string
  specificPlaceholder: string
  Icon: typeof Settings2
}

const MODES: ModeConfig[] = [
  {
    mode: 'machine-event',
    title: 'Machine Event',
    description: 'Record a machine or ECU-originated event.',
    specificLabel: 'Event type',
    specificPlaceholder: 'e.g. PRESSURE_WARNING',
    Icon: Settings2,
  },
  {
    mode: 'maintenance-record',
    title: 'Maintenance Record',
    description: 'Record an inspection, repair, or maintenance action.',
    specificLabel: 'Record type',
    specificPlaceholder: 'e.g. COMPONENT_INSPECTION',
    Icon: Wrench,
  },
  {
    mode: 'human-observation',
    title: 'Human Observation',
    description: 'Preserve an operator or technician observation as evidence.',
    specificLabel: 'Observation type',
    specificPlaceholder: 'e.g. OPERATOR_NOTE',
    Icon: UserRound,
  },
]

function defaultContextDimension(): ContextDimensionForm {
  return { value: '', quality: 'UNKNOWN', freshness_basis: '' }
}

function defaultValues(): EvidenceFormValues {
  return {
    machine_id: '',
    component_id: '',
    original_source_record_id: '',
    original_timestamp: '',
    source_specific: '',
    payload: '{}',
    raw_payload: '{}',
    provenance: '{}',
    context_enabled: false,
    context: {
      shift: defaultContextDimension(),
      location: defaultContextDimension(),
      machine_operating_state: defaultContextDimension(),
      workload: defaultContextDimension(),
      environment: defaultContextDimension(),
    },
    attachments: [],
  }
}

function parseJsonObject(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value)
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('Expected a JSON object.')
  }
  return parsed as Record<string, unknown>
}

function jsonValidation(value: string) {
  if (!value.trim()) return 'JSON is required.'
  try {
    parseJsonObject(value)
    return true
  } catch (error) {
    return error instanceof Error ? `Invalid JSON: ${error.message}` : 'Invalid JSON.'
  }
}

function contextLabel(key: ContextKey) {
  switch (key) {
    case 'machine_operating_state': return 'Machine operating state'
    case 'shift': return 'Shift'
    case 'location': return 'Location'
    case 'workload': return 'Workload'
    case 'environment': return 'Environment'
  }
}

function errorText(error: unknown) {
  if (error instanceof ApiError) {
    return error.code ? `${error.code}: ${error.message}` : error.message
  }
  return error instanceof Error ? error.message : 'The evidence request could not be completed.'
}

function fieldError(errors: FieldErrors<EvidenceFormValues>, name: keyof EvidenceFormValues) {
  const error = errors[name]
  return typeof error?.message === 'string' ? error.message : undefined
}

function JsonEditor({
  name,
  label,
  description,
  register,
  error,
}: {
  name: 'payload' | 'raw_payload' | 'provenance'
  label: string
  description: string
  register: UseFormRegister<EvidenceFormValues>
  error?: string
}) {
  return (
    <label className="evidence-json-editor">
      <span className="evidence-field__label"><Braces size={14} aria-hidden="true" />{label}</span>
      <span className="evidence-field__help">{description}</span>
      <textarea
        className="evidence-json-editor__input technical-text"
        spellCheck={false}
        rows={7}
        aria-invalid={Boolean(error)}
        {...register(name, { validate: jsonValidation })}
      />
      {error ? <span className="evidence-field__error" role="alert">{error}</span> : null}
    </label>
  )
}

function toContextInput(context: EvidenceFormValues['context']): ContextSnapshotInput {
  const result = {} as ContextSnapshotInput
  for (const key of CONTEXT_DIMENSIONS) {
    const dimension = context[key]
    result[key] = {
      value: dimension.quality === 'UNKNOWN' && !dimension.value.trim() ? null : dimension.value.trim(),
      quality: dimension.quality,
      freshness_basis: dimension.freshness_basis.trim(),
    } satisfies ContextDimensionInput
  }
  return result
}

function toAttachmentInput(attachment: AttachmentForm): AttachmentMetadataInput {
  const createdAt = localInputToIso(attachment.created_at)
  if (!createdAt) throw new Error('Attachment created_at is invalid.')
  return {
    attachment_type: attachment.attachment_type.trim(),
    storage_reference: attachment.storage_reference.trim(),
    mime_type: attachment.mime_type.trim(),
    file_size: Number(attachment.file_size),
    checksum: attachment.checksum.trim(),
    created_at: createdAt,
  }
}

function buildRequest(mode: EvidenceMode, values: EvidenceFormValues): EvidenceIngestionInput {
  const originalTimestamp = localInputToIso(values.original_timestamp)
  if (!originalTimestamp) throw new Error('Original timestamp is invalid.')

  const common = {
    machine_id: values.machine_id,
    ...(values.component_id ? { component_id: values.component_id } : {}),
    original_source_record_id: values.original_source_record_id.trim(),
    original_timestamp: originalTimestamp,
    payload: parseJsonObject(values.payload),
    raw_payload: parseJsonObject(values.raw_payload),
    provenance: parseJsonObject(values.provenance),
    ...(values.context_enabled ? { context_snapshot: toContextInput(values.context) } : {}),
    ...(values.attachments.length > 0 ? { attachments: values.attachments.map(toAttachmentInput) } : {}),
  }

  switch (mode) {
    case 'machine-event': return { ...common, event_type: values.source_specific.trim() }
    case 'maintenance-record': return { ...common, record_type: values.source_specific.trim() }
    case 'human-observation': return { ...common, observation_type: values.source_specific.trim() }
  }
}

export function AddEvidencePage() {
  const [mode, setMode] = useState<EvidenceMode>('machine-event')
  const mutation = useIngestEvidence()

  const {
    register,
    handleSubmit,
    watch,
    reset,
    resetField,
    setValue,
    control,
    formState: { errors },
  } = useForm<EvidenceFormValues>({ defaultValues: defaultValues() })

  const {
    fields: attachmentFields,
    append: appendAttachment,
    remove: removeAttachment,
  } = useFieldArray({ control, name: 'attachments' })

  const machineId = watch('machine_id')
  const contextEnabled = watch('context_enabled')
  const contextValues = watch('context')
  const machine = useCurrentMachine()
  const components = useCurrentMachineComponents()
  const foreignComponent = (components.data ?? []).find((component) => machine.data?.id && component.machine_id !== machine.data.id)
  const modeConfig = MODES.find((item) => item.mode === mode) ?? MODES[0]

  useEffect(() => {
    if (machine.data?.id && machineId !== machine.data.id) {
      setValue('machine_id', machine.data.id, { shouldValidate: true })
      resetField('component_id')
    }
  }, [machine.data?.id, machineId, resetField, setValue])

  const selectedMachine = machine.data

  function changeMode(nextMode: EvidenceMode) {
    if (nextMode === mode) return
    setMode(nextMode)
    resetField('source_specific')
    mutation.reset()
  }

  function submit(values: EvidenceFormValues) {
    const input = buildRequest(mode, values)
    mutation.mutate({ mode, input })
  }

  function startAnother() {
    mutation.reset()
    reset({ ...defaultValues(), machine_id: machine.data?.id ?? '' })
  }

  return (
    <>
      <PageIntro
        eyebrow="Controlled ingestion"
        title="Add Evidence"
        description="Record canonical machine evidence through one of the three backend-supported ingestion paths. Source identity, raw data, provenance, and evidence-time context remain explicit."
      />

      <GlassPanel className="page-panel evidence-mode-panel">
        <SectionHeader title="Evidence source" description="Choose exactly one supported ingestion path. Type vocabularies are entered as backend strings; no frontend-only controlled vocabulary is invented." />
        <div className="evidence-mode-tabs" role="tablist" aria-label="Evidence source type">
          {MODES.map(({ mode: itemMode, title, description, Icon }) => (
            <button
              key={itemMode}
              type="button"
              role="tab"
              aria-selected={mode === itemMode}
              className={`evidence-mode-tab${mode === itemMode ? ' evidence-mode-tab--active' : ''}`}
              onClick={() => changeMode(itemMode)}
            >
              <span className="evidence-mode-tab__icon"><Icon size={19} aria-hidden="true" /></span>
              <span><strong>{title}</strong><small>{description}</small></span>
            </button>
          ))}
        </div>
      </GlassPanel>

      {mutation.data ? (
        <GlassPanel className="page-panel evidence-success" aria-live="polite">
          <div className="evidence-success__icon"><CheckCircle2 size={22} aria-hidden="true" /></div>
          <div className="evidence-success__content">
            <StatusBadge tone="success">{mutation.data.idempotent_replay ? 'IDEMPOTENT REPLAY' : 'RECORDED'}</StatusBadge>
            <h2>{mutation.data.idempotent_replay ? 'Existing evidence reused — duplicate source record was not created again' : 'Evidence recorded'}</h2>
            <p>The backend returned the authoritative evidence identity below.</p>
            <TechnicalId value={mutation.data.evidence_id} />
            <div className="evidence-success__actions">
              {machineId ? (
                <Link className="button button--primary" to={`/machines/${encodeURIComponent(machineId)}#evidence-${encodeURIComponent(mutation.data.evidence_id)}`}>
                  <Link2 size={15} aria-hidden="true" />Open evidence in machine timeline
                </Link>
              ) : null}
              <button type="button" className="button button--ghost" onClick={startAnother}>Record another</button>
            </div>
          </div>
        </GlassPanel>
      ) : null}

      <form className="evidence-form" onSubmit={handleSubmit(submit)} noValidate>
        <GlassPanel className="page-panel">
          <SectionHeader title="Source identity" description="Machine and component identities come from the backend. The original source record ID is the idempotency identity within the source family." />

          <input type="hidden" {...register('machine_id', { required: 'Configured machine identity is unavailable.' })} />
          <div className="evidence-form-grid">
            <div className="evidence-field evidence-field--wide">
              <span className="evidence-field__label">Configured machine</span>
              <span className="evidence-field__help">Local evidence is always recorded against the backend-configured machine. No machine selector is exposed.</span>
              {machine.isPending ? <LoadingSkeleton width="100%" height={42} label="Configured machine loading" /> : null}
              {machine.isError ? <ErrorState title="Configured machine unavailable" description={errorText(machine.error)} /> : null}
              {selectedMachine ? (
                <div className="evidence-selected-machine">
                  <HardHat size={17} aria-hidden="true" />
                  <div><strong>{machineIdentity(selectedMachine)}</strong><span>{[machineProduct(selectedMachine), machineSite(selectedMachine)].filter(Boolean).join(' · ') || 'No additional machine metadata returned'}</span></div>
                  <TechnicalId value={selectedMachine.id} />
                </div>
              ) : null}
            </div>

            <label className="evidence-field">
              <span className="evidence-field__label">Component <span className="evidence-field__optional">optional</span></span>
              <select disabled={!machineId || components.isLoading} {...register('component_id')}>
                <option value="">Machine-level evidence</option>
                {components.data?.map((component) => <option key={component.id} value={component.id}>{component.display_name ?? component.component_type ?? component.id}</option>)}
              </select>
              {machineId && components.data?.length === 0 ? <span className="evidence-field__help">No components were returned for this machine.</span> : null}
            </label>

            <label className="evidence-field">
              <span className="evidence-field__label">Original source record ID</span>
              <input
                type="text"
                autoComplete="off"
                aria-invalid={Boolean(errors.original_source_record_id)}
                {...register('original_source_record_id', {
                  required: 'Original source record ID is required.',
                  validate: (value) => value.trim().length > 0 || 'Original source record ID cannot be blank.',
                })}
              />
              {errors.original_source_record_id?.message ? <span className="evidence-field__error" role="alert">{errors.original_source_record_id.message}</span> : null}
            </label>

            <label className="evidence-field">
              <span className="evidence-field__label">Original timestamp</span>
              <input
                type="datetime-local"
                aria-invalid={Boolean(errors.original_timestamp)}
                {...register('original_timestamp', {
                  required: 'Original timestamp is required.',
                  validate: (value) => Boolean(localInputToIso(value)) || 'Enter a valid timestamp.',
                })}
              />
              {errors.original_timestamp?.message ? <span className="evidence-field__error" role="alert">{errors.original_timestamp.message}</span> : null}
            </label>

            <label className="evidence-field evidence-field--wide">
              <span className="evidence-field__label">{modeConfig.specificLabel}</span>
              <span className="evidence-field__help">Free text by contract. The backend does not expose a controlled dropdown vocabulary for this field.</span>
              <input
                type="text"
                placeholder={modeConfig.specificPlaceholder}
                aria-invalid={Boolean(errors.source_specific)}
                {...register('source_specific', {
                  required: `${modeConfig.specificLabel} is required.`,
                  validate: (value) => value.trim().length > 0 || `${modeConfig.specificLabel} cannot be blank.`,
                })}
              />
              {errors.source_specific?.message ? <span className="evidence-field__error" role="alert">{errors.source_specific.message}</span> : null}
            </label>
          </div>

          {components.isError ? <ErrorState title="Components unavailable" description={errorText(components.error)} /> : null}
          {foreignComponent ? <ErrorState title="Machine-scope violation" description="The backend returned a component for another machine. Evidence submission is disabled until the configured-machine component contract is consistent." /> : null}
        </GlassPanel>

        <GlassPanel className="page-panel">
          <SectionHeader title="Canonical source data" description="These fields are submitted as structured JSON. Raw source data and provenance stay visible rather than being hidden behind a simplified form." />
          <div className="evidence-json-grid">
            <JsonEditor name="payload" label="Payload" description="Normalized/structured source payload supplied to canonical ingestion." register={register} error={fieldError(errors, 'payload')} />
            <JsonEditor name="raw_payload" label="Raw payload" description="Original source details preserved for inspection and traceability." register={register} error={fieldError(errors, 'raw_payload')} />
            <JsonEditor name="provenance" label="Provenance" description="Structured information describing where this source record came from." register={register} error={fieldError(errors, 'provenance')} />
          </div>
        </GlassPanel>

        <GlassPanel className="page-panel">
          <div className="evidence-section-header">
            <SectionHeader title="Context snapshot" description="Optional historical context captured at evidence time. If enabled, all five fixed dimensions are submitted with value, quality, and freshness basis." />
            <label className="evidence-toggle"><input type="checkbox" {...register('context_enabled')} /><span>Include context snapshot</span></label>
          </div>

          {contextEnabled ? (
            <div className="context-form-grid">
              {CONTEXT_DIMENSIONS.map((key) => {
                const quality = contextValues?.[key]?.quality ?? 'UNKNOWN'
                return (
                  <GlassCard className="context-form-card" key={key}>
                    <div className="context-form-card__header"><strong>{contextLabel(key)}</strong><StatusBadge tone={quality === 'KNOWN' ? 'success' : quality === 'STALE' ? 'warning' : 'neutral'}>{quality}</StatusBadge></div>
                    <label className="evidence-field">
                      <span className="evidence-field__label">Value</span>
                      <input
                        type="text"
                        placeholder={quality === 'UNKNOWN' ? 'May remain blank when quality is UNKNOWN' : 'Enter observed value'}
                        {...register(`context.${key}.value`, {
                          validate: (value) => {
                            if (!contextEnabled || quality === 'UNKNOWN') return true
                            return value.trim().length > 0 || 'Value is required for KNOWN or STALE context.'
                          },
                        })}
                      />
                      {errors.context?.[key]?.value?.message ? <span className="evidence-field__error" role="alert">{errors.context[key]?.value?.message}</span> : null}
                    </label>
                    <label className="evidence-field">
                      <span className="evidence-field__label">Quality</span>
                      <select {...register(`context.${key}.quality`)}>
                        {QUALITY_VALUES.map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                    </label>
                    <label className="evidence-field">
                      <span className="evidence-field__label">Freshness basis</span>
                      <input
                        type="text"
                        placeholder="Source timestamp or documented freshness basis"
                        {...register(`context.${key}.freshness_basis`, {
                          validate: (value) => !contextEnabled || value.trim().length > 0 || 'Freshness basis is required.',
                        })}
                      />
                      {errors.context?.[key]?.freshness_basis?.message ? <span className="evidence-field__error" role="alert">{errors.context[key]?.freshness_basis?.message}</span> : null}
                    </label>
                  </GlassCard>
                )
              })}
            </div>
          ) : <div className="evidence-optional-empty"><Info size={16} aria-hidden="true" />No context snapshot will be submitted.</div>}
        </GlassPanel>

        <GlassPanel className="page-panel">
          <div className="evidence-section-header">
            <SectionHeader title="Attachment metadata" description="Optional metadata references only. Adding a record here does not upload, record, transcribe, play, or download a binary file." />
            <button
              type="button"
              className="button button--ghost"
              onClick={() => appendAttachment({ attachment_type: '', storage_reference: '', mime_type: '', file_size: '', checksum: '', created_at: '' })}
            >
              <Plus size={15} aria-hidden="true" />Add metadata
            </button>
          </div>

          <div className="attachment-metadata-warning"><Paperclip size={16} aria-hidden="true" /><span><strong>Attachment metadata</strong> — a storage reference is descriptive metadata and is not proof that the browser can access the referenced binary.</span></div>

          {attachmentFields.length === 0 ? (
            <EmptyState title="No attachment metadata" description="This evidence will be submitted without attachment metadata." />
          ) : (
            <div className="attachment-form-list">
              {attachmentFields.map((field, index) => (
                <GlassCard className="attachment-form-card" key={field.id}>
                  <div className="attachment-form-card__header"><strong>Metadata record {index + 1}</strong><button type="button" className="icon-button" aria-label={`Remove attachment metadata ${index + 1}`} onClick={() => removeAttachment(index)}><Trash2 size={15} /></button></div>
                  <div className="attachment-form-grid">
                    <label className="evidence-field"><span className="evidence-field__label">Attachment type</span><input type="text" {...register(`attachments.${index}.attachment_type`, { required: 'Attachment type is required.', validate: (value) => value.trim().length > 0 || 'Attachment type cannot be blank.' })} />{errors.attachments?.[index]?.attachment_type?.message ? <span className="evidence-field__error" role="alert">{errors.attachments[index]?.attachment_type?.message}</span> : null}</label>
                    <label className="evidence-field"><span className="evidence-field__label">Storage reference</span><input type="text" {...register(`attachments.${index}.storage_reference`, { required: 'Storage reference is required.', validate: (value) => value.trim().length > 0 || 'Storage reference cannot be blank.' })} />{errors.attachments?.[index]?.storage_reference?.message ? <span className="evidence-field__error" role="alert">{errors.attachments[index]?.storage_reference?.message}</span> : null}</label>
                    <label className="evidence-field"><span className="evidence-field__label">MIME type</span><input type="text" {...register(`attachments.${index}.mime_type`, { required: 'MIME type is required.', validate: (value) => value.trim().length > 0 || 'MIME type cannot be blank.' })} />{errors.attachments?.[index]?.mime_type?.message ? <span className="evidence-field__error" role="alert">{errors.attachments[index]?.mime_type?.message}</span> : null}</label>
                    <label className="evidence-field"><span className="evidence-field__label">File size (bytes)</span><input type="number" min="0" step="1" {...register(`attachments.${index}.file_size`, { required: 'File size is required.', validate: (value) => (Number.isFinite(Number(value)) && Number(value) >= 0 && Number.isInteger(Number(value))) || 'File size must be a non-negative integer.' })} />{errors.attachments?.[index]?.file_size?.message ? <span className="evidence-field__error" role="alert">{errors.attachments[index]?.file_size?.message}</span> : null}</label>
                    <label className="evidence-field"><span className="evidence-field__label">Checksum</span><input type="text" {...register(`attachments.${index}.checksum`, { required: 'Checksum is required.', validate: (value) => value.trim().length > 0 || 'Checksum cannot be blank.' })} />{errors.attachments?.[index]?.checksum?.message ? <span className="evidence-field__error" role="alert">{errors.attachments[index]?.checksum?.message}</span> : null}</label>
                    <label className="evidence-field"><span className="evidence-field__label">Created at</span><input type="datetime-local" {...register(`attachments.${index}.created_at`, { required: 'Created at is required.', validate: (value) => Boolean(localInputToIso(value)) || 'Enter a valid created timestamp.' })} />{errors.attachments?.[index]?.created_at?.message ? <span className="evidence-field__error" role="alert">{errors.attachments[index]?.created_at?.message}</span> : null}</label>
                  </div>
                </GlassCard>
              ))}
            </div>
          )}
        </GlassPanel>

        {mutation.isError ? <ErrorState title="Evidence was not recorded" description={errorText(mutation.error)} /> : null}

        <GlassPanel className="page-panel evidence-submit-panel">
          <div className="evidence-submit-panel__copy"><ClipboardPlus size={20} aria-hidden="true" /><div><strong>Submit {modeConfig.title}</strong><span>The backend remains responsible for identity validation, idempotency, canonical persistence, incident linking, and downstream lifecycle effects.</span></div></div>
          <button type="submit" className="button button--primary" disabled={mutation.isPending || machine.isError || !machineId || Boolean(foreignComponent)}>{mutation.isPending ? 'Recording…' : 'Record evidence'}</button>
        </GlassPanel>
      </form>
    </>
  )
}
