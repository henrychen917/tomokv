set pagination off
set print pretty on
frame 6
p this->atomic_pending_
p this->atomic_pending_->live
p this->atomic_pending_->script_intent_count
p *this->atomic_pending_->script_intents
p this->atomic_pending_->script_intents->next
p *this->atomic_pending_->script_intents->next
info frame
x/12i $pc-40
