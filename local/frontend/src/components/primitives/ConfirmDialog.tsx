import { useEffect, useId, useRef } from 'react'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
    }
  }, [open])

  return (
    <dialog ref={ref} className="confirm-dialog" aria-labelledby={titleId} aria-describedby={descriptionId} aria-modal="true" onCancel={(event) => { event.preventDefault(); onCancel() }}>
      <div className="confirm-dialog__content">
        <h2 id={titleId} className="confirm-dialog__title">{title}</h2>
        <p id={descriptionId} className="confirm-dialog__description">{description}</p>
        <div className="confirm-dialog__actions">
          <button className="button" type="button" autoFocus onClick={onCancel}>{cancelLabel}</button>
          <button className={destructive ? 'button button--danger' : 'button button--primary'} type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  )
}
