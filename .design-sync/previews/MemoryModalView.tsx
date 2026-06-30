import React from 'react'
import { MemoryModalView } from 'agent-frontend'

// Agent memory editor: free-text working memory plus the structured facts the
// agent has distilled from prior turns over the e-commerce order dataset.
export const Editing = () => (
  <MemoryModalView
    open={true}
    loading={false}
    error={null}
    saving={false}
    saveError={null}
    text="The user works with e-commerce order data. Prefer revenue in USD. 'Region' means shipping region, not billing."
    facts={[
      'Revenue is in USD',
      'Region = shipping region',
      'Orders join customers on customer_id',
    ]}
    savedAt={null}
    textareaRef={{ current: null } as React.RefObject<HTMLTextAreaElement | null>}
    onTextChange={() => {}}
    onRetry={() => {}}
    onSave={() => {}}
    onClose={() => {}}
  />
)
