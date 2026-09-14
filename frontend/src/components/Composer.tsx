import { useRef, useState } from 'react'

const MAX_CHARS = 8000

interface Props {
  disabled: boolean
  busy: boolean
  onSend: (text: string) => void
}

export function Composer({ disabled, busy, onSend }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const trimmed = value.trim()
  const tooLong = value.length > MAX_CHARS
  const canSend = trimmed.length > 0 && !tooLong && !busy && !disabled

  function submit() {
    if (!canSend) return
    onSend(trimmed)
    setValue('')
    textareaRef.current?.focus()
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter inserts a newline.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <label className="visually-hidden" htmlFor="composer-input">
        Ask a product or growth question
      </label>
      <textarea
        id="composer-input"
        ref={textareaRef}
        rows={2}
        value={value}
        placeholder={disabled ? 'Start a new chat to begin' : 'Ask about product, growth, or request an essay or artifact…'}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled || busy}
        aria-describedby="composer-hint"
        aria-invalid={tooLong}
      />
      <div className="composer__actions">
        <span id="composer-hint" className={`composer__hint${tooLong ? ' is-error' : ''}`}>
          {tooLong
            ? `${value.length.toLocaleString()} / ${MAX_CHARS.toLocaleString()} characters — too long`
            : 'Enter to send · Shift+Enter for a new line'}
        </span>
        <button type="submit" disabled={!canSend}>
          {busy ? 'Working…' : 'Send'}
        </button>
      </div>
    </form>
  )
}
