import { useState } from 'react';
import { Text, View } from 'react-native';
import { useQuery, useMutation } from '@tanstack/react-query';
import { router } from 'expo-router';
import { api, fixture } from '../lib/api';
import { useSession } from '../lib/session';
import { Button, ErrorText, Field, Screen, styles } from '../components/ui';
export default function Home() {
  const session = useSession();
  const [email, setEmail] = useState(''), [password, setPassword] = useState('');
  const users = useQuery({ queryKey: ['fixture-users'], queryFn: () => api<Array<{ id: string; name: string }>>('/fixture/users'), enabled: fixture });
  const login = useMutation({ mutationFn: (id: string) => fixture ? session.loginFixture(id) : session.login(email, password), onSuccess: () => router.push('/profile') });
  const logout = useMutation({ mutationFn: session.logout });
  return <Screen title="Find your kind of home.">
    <Text style={styles.text}>Meet a roommate before finding a place. Shared routines, compatible budgets, better conversations.</Text>
    {session.loading ? <Text>Restoring session…</Text> : session.token ? <View style={styles.card}>
      <Text style={styles.text}>You’re signed in. Start with your profile, then discover your next FlatPal.</Text>
      <Button title="Discover roommates" onPress={() => router.push('/discover')} />
      <Button title="Sign out / switch demo user" disabled={logout.isPending} onPress={() => logout.mutate()} />
    </View> : fixture ? <View style={styles.card}>
      <Text style={styles.text}>Fictional demo identities. Choose Alex, like Sam, then switch to Sam and like Alex to create a match. Demo tokens expire after one hour.</Text>
      {users.data?.map(user => <Button key={user.id} title={`Continue as ${user.name}`} disabled={login.isPending} onPress={() => login.mutate(user.id)} />)}
    </View> : <View style={styles.card}>
      <Text style={styles.text}>Use a Supabase demo account provisioned by the developer.</Text>
      <Field label="Email" value={email} onChange={setEmail} /><Field label="Password" value={password} onChange={setPassword} secret />
      <Button title="Sign in" disabled={login.isPending} onPress={() => login.mutate('')} />
    </View>}
    <ErrorText error={users.error ?? login.error ?? logout.error} />
  </Screen>;
}
