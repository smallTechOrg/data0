import { UploadCard } from 'agent-frontend'

// Upload card: the standalone file drop zone with its empty staging queue.
// `onUploaded` is the only prop (a required refresh callback fired after each
// successful upload) — wired here as a no-op.
export const DropZone = () => <UploadCard onUploaded={() => {}} />
