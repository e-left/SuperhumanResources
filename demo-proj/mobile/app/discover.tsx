import { useState } from 'react';
import { Alert, Text, View } from 'react-native';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, Profile } from '../lib/api';
import { useSession } from '../lib/session';
import { Button, ErrorText, Field, Screen, styles } from '../components/ui';
import { SwipeCard } from '../components/swipe-card';
export default function Discovery() {
  const { token } = useSession(), cache = useQueryClient();
  const [radius, setRadius] = useState('10'), [days, setDays] = useState('30');
  const [min, setMin] = useState('900'), [max, setMax] = useState('1600');
  const [filters, setFilters] = useState('radiusKm=10&moveInDays=30&budgetMin=900&budgetMax=1600');
  const cards = useQuery({ queryKey: ['discovery', filters], queryFn: () => api<Profile[]>(`/discovery?${filters}`, token), enabled: !!token });
  const card = cards.data?.[0];
  const refresh = () => { cache.invalidateQueries({ queryKey: ['discovery'] }); cache.invalidateQueries({ queryKey: ['matches'] }); };
  const swipe = useMutation({ mutationFn: (decision: 'like' | 'pass') => api<{ matchId: string | null }>('/swipes', token, { targetId: card!.id, decision }), onSuccess: result => {
    refresh(); if (result.matchId) Alert.alert('It’s a match!', 'Open Matches to say hello.');
  } });
  const block = useMutation({ mutationFn: () => api('/blocks', token, { targetId: card!.id }), onSuccess: refresh });
  const busy = swipe.isPending || block.isPending || cards.isFetching;
  return <Screen title="Meet your next FlatPal">
    {!token ? <Text>Sign in on Home first.</Text> : <>
      <Field label="Budget minimum (CHF)" value={min} onChange={setMin} numeric /><Field label="Budget maximum (CHF)" value={max} onChange={setMax} numeric />
      <Field label="Distance (km)" value={radius} onChange={setRadius} numeric /><Field label="Move-in tolerance (days)" value={days} onChange={setDays} numeric />
      <Button title="Apply filters" disabled={busy} onPress={() => setFilters(`radiusKm=${encodeURIComponent(radius)}&moveInDays=${encodeURIComponent(days)}&budgetMin=${encodeURIComponent(min)}&budgetMax=${encodeURIComponent(max)}`)} />
      {cards.isPending ? <Text>Loading cards…</Text> : card ? <>
        <SwipeCard key={card.id} profile={card} pending={busy} onSwipe={decision => { if (!busy) swipe.mutate(decision); }} />
        <View style={styles.row}><Button title="Pass" disabled={busy} onPress={() => swipe.mutate('pass')} /><Button title="Like" disabled={busy} onPress={() => swipe.mutate('like')} /><Button title="Block" disabled={busy} onPress={() => block.mutate()} /></View>
      </> : <Text style={styles.text}>No more compatible profiles. Change your filters or switch demo users on Home.</Text>}
    </>}
    <ErrorText error={cards.error ?? swipe.error ?? block.error} />
  </Screen>;
}
