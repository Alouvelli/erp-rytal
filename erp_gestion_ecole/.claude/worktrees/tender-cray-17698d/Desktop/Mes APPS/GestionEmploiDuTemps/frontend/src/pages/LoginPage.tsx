import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { useAuth } from '../context/AuthContext';
import { AcademicCapIcon, EyeIcon, EyeSlashIcon } from '@heroicons/react/24/outline';
import toast from 'react-hot-toast';

interface Form { email: string; password: string; }

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [showPwd, setShowPwd] = useState(false);
  const { register, handleSubmit, formState: { isSubmitting, errors } } = useForm<Form>();

  const onSubmit = async (data: Form) => {
    try {
      await login(data.email, data.password);
      toast.success('Connexion réussie !');
      navigate('/dashboard');
    } catch {
      toast.error('Email ou mot de passe incorrect');
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-900 via-primary-800 to-gray-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-white/10 backdrop-blur rounded-2xl mb-4">
            <AcademicCapIcon className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-white">GestionEDT</h1>
          <p className="text-primary-200 mt-1">Système de gestion académique universitaire</p>
        </div>

        {/* Card */}
        <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl p-8">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-6">Connexion</h2>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div>
              <label className="label">Adresse email</label>
              <input type="email" className="input" placeholder="vous@universite.fr"
                {...register('email', { required: 'Email requis' })} />
              {errors.email && <p className="text-xs text-red-500 mt-1">{errors.email.message}</p>}
            </div>

            <div>
              <label className="label">Mot de passe</label>
              <div className="relative">
                <input type={showPwd ? 'text' : 'password'} className="input pr-10" placeholder="••••••••"
                  {...register('password', { required: 'Mot de passe requis' })} />
                <button type="button" onClick={() => setShowPwd(!showPwd)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showPwd ? <EyeSlashIcon className="w-4 h-4" /> : <EyeIcon className="w-4 h-4" />}
                </button>
              </div>
              {errors.password && <p className="text-xs text-red-500 mt-1">{errors.password.message}</p>}
            </div>

            <button type="submit" disabled={isSubmitting}
              className="btn-primary w-full justify-center py-2.5 text-base mt-2 disabled:opacity-60">
              {isSubmitting ? <span className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" /> : null}
              {isSubmitting ? 'Connexion...' : 'Se connecter'}
            </button>
          </form>

          {/* Demo accounts */}
          <div className="mt-6 pt-4 border-t border-gray-100 dark:border-gray-800">
            <p className="text-xs text-gray-500 text-center mb-3">Comptes de démonstration</p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {[
                { role: 'Admin', email: 'admin@universite.fr', pwd: 'Admin@1234' },
                { role: 'Scolarité', email: 'scolarite@universite.fr', pwd: 'Scol@1234' },
                { role: 'Enseignant', email: 'prof.martin@universite.fr', pwd: 'Prof@1234' },
                { role: 'Étudiant', email: 'alice.dupont@etu.fr', pwd: 'Student@1234' },
              ].map(acc => (
                <button key={acc.role} onClick={() => { document.querySelector<HTMLInputElement>('input[type=email]')!.value = acc.email; }}
                  className="p-2 bg-gray-50 dark:bg-gray-800 rounded-lg text-left hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                  <span className="font-medium text-gray-700 dark:text-gray-200 block">{acc.role}</span>
                  <span className="text-gray-400 truncate block">{acc.email}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
