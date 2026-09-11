import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { authApi } from '../services/api';
import { useForm } from 'react-hook-form';
import toast from 'react-hot-toast';
import { UserCircleIcon, KeyIcon } from '@heroicons/react/24/outline';

const ROLE_LABELS: Record<string, string> = {
  ADMIN: 'Administrateur', SCOLARITE: 'Responsable Scolarité', TEACHER: 'Enseignant', STUDENT: 'Étudiant',
};

export default function ProfilePage() {
  const { user } = useAuth();
  const [tab, setTab] = useState('info');
  const { register, handleSubmit, reset, formState: { isSubmitting } } = useForm();

  const changePassword = async (data: any) => {
    if (data.newPassword !== data.confirm) { toast.error('Les mots de passe ne correspondent pas'); return; }
    try {
      await authApi.changePassword({ currentPassword: data.currentPassword, newPassword: data.newPassword });
      toast.success('Mot de passe modifié');
      reset();
    } catch (e: any) { toast.error(e.response?.data?.message || 'Erreur'); }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Mon profil</h1>

      <div className="card p-6">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-16 h-16 rounded-full bg-primary-600 flex items-center justify-center text-white text-2xl font-bold">
            {user?.firstName?.[0]}{user?.lastName?.[0]}
          </div>
          <div>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{user?.firstName} {user?.lastName}</h2>
            <p className="text-gray-500">{user?.email}</p>
            <span className="badge badge-blue mt-1">{ROLE_LABELS[user?.role ?? ''] ?? user?.role}</span>
          </div>
        </div>

        {/* Tabs */}
        <div className="border-b border-gray-200 dark:border-gray-800 mb-6">
          <nav className="flex gap-1 -mb-px">
            {[{ id: 'info', label: 'Informations', icon: UserCircleIcon }, { id: 'password', label: 'Sécurité', icon: KeyIcon }].map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  tab === t.id ? 'border-primary-600 text-primary-600' : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}>
                <t.icon className="w-4 h-4" /> {t.label}
              </button>
            ))}
          </nav>
        </div>

        {tab === 'info' && (
          <div className="grid grid-cols-2 gap-4 text-sm">
            {[
              { label: 'Prénom', value: user?.firstName },
              { label: 'Nom', value: user?.lastName },
              { label: 'Email', value: user?.email },
              { label: 'Téléphone', value: user?.phone ?? 'Non renseigné' },
              { label: 'Rôle', value: ROLE_LABELS[user?.role ?? ''] ?? user?.role },
            ].map(f => (
              <div key={f.label}>
                <p className="text-gray-500 text-xs font-medium uppercase tracking-wide">{f.label}</p>
                <p className="font-medium text-gray-900 dark:text-white mt-0.5">{f.value}</p>
              </div>
            ))}
          </div>
        )}

        {tab === 'password' && (
          <form onSubmit={handleSubmit(changePassword)} className="space-y-4 max-w-sm">
            <div>
              <label className="label">Mot de passe actuel</label>
              <input type="password" className="input" {...register('currentPassword', { required: true })} />
            </div>
            <div>
              <label className="label">Nouveau mot de passe</label>
              <input type="password" className="input" {...register('newPassword', { required: true, minLength: 8 })} />
            </div>
            <div>
              <label className="label">Confirmer le mot de passe</label>
              <input type="password" className="input" {...register('confirm', { required: true })} />
            </div>
            <button type="submit" disabled={isSubmitting} className="btn-primary disabled:opacity-60">
              {isSubmitting ? 'Mise à jour...' : 'Modifier le mot de passe'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
